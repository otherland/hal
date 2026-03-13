# Plan: `hal` — Harmful Action Limiter

## Context

dcg is a 147K LOC Rust tool that blocks destructive commands from AI agents. We're rewriting the core value as `hal` in Python — targeting **~400 LOC**.

## The Breakthrough: Token-Level Matching

dcg's architecture: regex match against command strings → requires 3300-line sanitizer to avoid false positives on data like `git commit -m "fix rm -rf"`.

Our architecture: `shlex.split()` → match against **token lists** → false positives **don't exist**.

```
"git commit -m 'fix rm -rf detection'"
  → shlex.split → ["git", "commit", "-m", "fix rm -rf detection"]
  → rule: command=git, has_all=[reset, --hard]
  → "reset" not in tokens → NO MATCH
  → The commit message is ONE opaque token. We never look inside it.
```

**Proved with 27/27 test cases — zero false positives, zero sanitizer code.**

Rules that took regex like `git\s+(?:\S+\s+)*push\s+.*(?:--force(?!-with-lease)|-f\b)` become:
```yaml
- name: push-force
  command: git
  has_all: [push]
  has_any: [--force, -f]
  unless: [--force-with-lease]
```

Readable by anyone. No regex knowledge needed.

## Project Structure

```
hal/
├── pyproject.toml
├── hal/
│   ├── __init__.py             # Version (~5 LOC)
│   ├── __main__.py             # CLI: hook (default), test, install (~80 LOC)
│   ├── evaluate.py             # Pipeline: normalize → tokenize → match (~200 LOC)
│   └── packs.py                # Load YAML, compile rules (~60 LOC)
├── packs/
│   ├── core.git.yaml
│   ├── core.filesystem.yaml
│   ├── containers.docker.yaml
│   ├── cloud.aws.yaml
│   └── cloud.azure.yaml
└── tests/
    ├── test_evaluate.py
    ├── test_packs.py
    └── test_hook.py
```

**~400 LOC Python + ~500 LOC YAML packs. No sanitizer module.**

## YAML Pack Format (Token-Based Rules)

```yaml
id: core.git
name: Core Git
keywords: [git]

rules:
  # Token-based rules (primary — no regex needed)
  - name: reset-hard
    command: git
    has_all: [reset, --hard]
    severity: critical
    reason: "Discards all uncommitted changes permanently."

  - name: push-force
    command: git
    has_all: [push]
    has_any: [--force, -f]
    unless: [--force-with-lease]
    severity: critical
    reason: "Rewrites remote history. Use --force-with-lease instead."

  - name: clean-force
    command: git
    has_all: [clean]
    has_any: [--force, -f]
    unless: [-n, --dry-run]
    severity: critical
    reason: "Permanently removes untracked files."

  - name: stash-clear
    command: git
    has_all: [stash, clear]
    severity: critical
    reason: "Wipes ALL stashes. Very difficult to recover."

  - name: stash-drop
    command: git
    has_all: [stash, drop]
    severity: medium
    reason: "Deletes a stash entry."

  - name: branch-force-delete
    command: git
    has_all: [branch]
    has_any: [-D, --force, -f]
    severity: medium
    reason: "Force-deletes branch without merge check."

  - name: checkout-discard
    command: git
    has_all: [checkout, --]
    severity: high
    reason: "Discards uncommitted changes. Use 'git stash' first."

  - name: restore-worktree
    command: git
    has_all: [restore]
    unless: [--staged, -S]
    severity: high
    reason: "Discards uncommitted working directory changes."

  # Regex fallback (for patterns that need positional/structural matching)
  - name: push-force-short
    pattern: 'git\s+push\s+.*-f\b'
    severity: critical
    reason: "Short-form force push."
```

### Rule Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Unique name within pack |
| `command` | string | for token rules | The executable (first token) |
| `has_all` | list | no | ALL of these must be in tokens |
| `has_any` | list | no | At least ONE must be in tokens or flags |
| `unless` | list | no | If ANY present → rule does NOT match (replaces safe_patterns) |
| `flags_contain` | list | no | Individual flag chars (e.g. `[r, f]` matches `-rf`, `-r -f`, `--recursive --force`) |
| `unless_path` | list | no | Glob patterns for allowed paths (e.g. `/tmp/*`) |
| `pattern` | string | for regex rules | Regex fallback (matched against full command string) |
| `severity` | string | yes | `critical`, `high`, `medium`, `low` |
| `reason` | string | yes | Human-readable explanation |

**Token-based rules have NO separate safe_patterns.** The `unless` clause is built into the rule itself.

## The Pipeline (evaluate.py)

```python
def evaluate(command: str, packs, config, _depth=0) -> Decision:
    # 1. Config allow overrides
    if command in config.allow or any(command.startswith(p) for p in config.allow_prefixes):
        return ALLOW

    # 2. Normalize: strip sudo/env/backslash/abs-paths
    command = normalize(command)

    # 3. Keyword pre-filter
    relevant = [p for p in packs if any(kw in command for kw in p.keywords)]
    if not relevant:
        return ALLOW

    # 4. Split on | && || ; — evaluate each segment
    for segment in split_segments(command):
        decision = evaluate_segment(segment, relevant, config, _depth)
        if not decision.allow:
            return decision
    return ALLOW

def evaluate_segment(segment, packs, config, _depth):
    # 5. Tokenize with shlex
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()  # fail-open

    if not tokens:
        return ALLOW

    # 6. Inline script extraction (bash -c, python -c — recurse once)
    if _depth == 0:
        inline = extract_inline(tokens)
        if inline:
            d = evaluate(inline, packs, config, _depth=1)
            if not d.allow:
                return d

    # 7. Heredoc extraction (bash <<EOF — recurse once per line)
    if _depth == 0:
        body = extract_heredoc(segment)
        if body:
            for line in body.splitlines():
                line = line.strip()
                if line and not line.startswith('#'):
                    d = evaluate(line, packs, config, _depth=1)
                    if not d.allow:
                        return d

    # 8. Match rules
    flags = parse_flags(tokens)
    for pack in packs:
        for rule in pack.rules:
            if rule.pattern:
                # Regex fallback: need sanitized string
                sanitized = sanitize(tokens)
                if rule.compiled.search(sanitized):
                    if rule.rule_id not in config.allow_rules:
                        return DENY(rule.rule_id, rule.reason)
            else:
                # Token-based: no sanitization needed
                if match_rule(tokens, flags, rule):
                    if rule.rule_id not in config.allow_rules:
                        return DENY(rule.rule_id, rule.reason)
    return ALLOW
```

## Token Matching (~30 LOC)

```python
def parse_flags(tokens):
    """Expand combined short flags: -rf → {-r, -f}, --force → {--force}"""
    flags = set()
    for tok in tokens:
        if tok.startswith("--"):
            flags.add(tok)
            if "=" in tok:
                flags.add(tok.split("=")[0])
        elif tok.startswith("-") and len(tok) > 1 and not tok[1].isdigit():
            for c in tok[1:]:
                flags.add(f"-{c}")
    return flags

def match_rule(tokens, flags, rule):
    if tokens[0] != rule.command:
        return False
    all_tokens = set(tokens)
    combined = all_tokens | flags
    if rule.has_all and not all(t in all_tokens for t in rule.has_all):
        return False
    if rule.has_any and not any(t in combined for t in rule.has_any):
        return False
    if rule.flags_contain:
        for fc in rule.flags_contain:
            if f"-{fc}" not in flags:
                return False
    if rule.unless and any(t in combined for t in rule.unless):
        return False
    return True
```

## Sanitizer (~30 LOC, only for regex fallback rules)

Only called when a rule uses `pattern` instead of token matching. Most packs won't need this.

```python
ALL_ARGS_DATA = {"echo", "printf"}
FLAG_DATA = {
    "git": {"-m", "--message", "--grep"},
    "grep": {"-e", "--regexp"}, "rg": {"-e", "--regexp"},
    "curl": {"-d", "--data", "-H", "--header"},
    "gh": {"-t", "--title", "-b", "--body"},
}

def sanitize(tokens):
    """Mask data tokens for regex fallback rules."""
    if not tokens:
        return ""
    cmd, out, skip = tokens[0], [], False
    for i, tok in enumerate(tokens):
        if skip:
            skip = False; out.append("_" * len(tok)); continue
        if i > 0 and cmd in ALL_ARGS_DATA and "$(" not in tok and "`" not in tok:
            out.append("_" * len(tok)); continue
        if cmd in FLAG_DATA and tok in FLAG_DATA[cmd]:
            skip = True; out.append(tok); continue
        out.append(tok)
    return " ".join(out)
```

## Normalizer (~25 LOC)

```python
KNOWN_BINS = {"git", "rm", "docker", "kubectl", "aws", "az", "bash", "sh", "python", "python3"}

def normalize(command):
    prev = None
    while command != prev:
        prev = command
        command = command.lstrip("\\")
        command = re.sub(r"^sudo\s+(?:-\S+\s+)*", "", command)
        command = re.sub(r"^env\s+(?:-\S+\s+|\S+=\S+\s+)*", "", command)
        m = re.match(r"^command\s+(-[^vV]\S*\s+|--\s+)*", command)
        if m and not re.match(r"^command\s+-[vV]", command):
            command = command[m.end():]
        for b in KNOWN_BINS:
            command = re.sub(rf"^(/usr(/local)?)?/s?bin/{b}\b", b, command)
    return command.strip()
```

## Inline Script + Heredoc Extraction (~40 LOC)

```python
INTERPRETERS = {"bash", "sh", "zsh", "fish", "python", "python3", "ruby", "perl", "node"}
INLINE_FLAGS = {"bash": "-c", "sh": "-c", "zsh": "-c", "python": "-c",
                "python3": "-c", "ruby": "-e", "perl": "-e", "node": "-e"}

def extract_inline(tokens):
    if len(tokens) < 3: return None
    flag = INLINE_FLAGS.get(tokens[0])
    if not flag: return None
    try:
        idx = tokens.index(flag)
        return tokens[idx + 1] if idx + 1 < len(tokens) else None
    except ValueError: return None

def extract_heredoc(command):
    m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", command)
    if not m: return None
    delim = m.group(1)
    lines = command.split("\n")
    body, capturing = [], False
    for line in lines:
        if capturing:
            if line.strip() == delim: break
            body.append(line)
        elif "<<" in line and delim in line:
            capturing = True
    if not body: return None
    # Only evaluate if piped to or invoked by an interpreter
    before = command[:m.start()].strip().split()
    if before and before[0] in INTERPRETERS: return "\n".join(body)
    if "|" in command:
        targets = [s.strip().split()[0] for s in command.split("|")[1:] if s.strip()]
        if any(t in INTERPRETERS for t in targets): return "\n".join(body)
    return None
```

## Hook Protocol — Copilot (default) + Claude Code

**Auto-detected from input JSON.**

### Copilot Input
```json
{"event": "pre-tool-use", "toolName": "run_shell_command", "toolInput": {"command": "..."}}
```
or with `toolArgs` as JSON string:
```json
{"event": "pre-tool-use", "toolName": "bash", "toolArgs": "{\"command\":\"...\"}"}
```

### Claude Code Input
```json
{"tool_name": "Bash", "tool_input": {"command": "..."}}
```

### Output

**Copilot deny:**
```json
{"continue": false, "stopReason": "BLOCKED: ...", "permissionDecision": "deny", "permissionDecisionReason": "..."}
```

**Claude Code deny:**
```json
{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}
```

**Allow (both):** exit 0, empty stdout.

```python
def detect_protocol(hook_input):
    tool = hook_input.get("tool_name") or hook_input.get("toolName") or ""
    if tool in ("run_shell_command", "run-shell-command") or hook_input.get("event") == "pre-tool-use":
        return "copilot"
    return "claude"

def extract_command(hook_input):
    ti = hook_input.get("tool_input") or hook_input.get("toolInput") or {}
    if isinstance(ti, dict) and "command" in ti:
        return str(ti["command"]) if ti["command"] is not None else None
    ta = hook_input.get("toolArgs") or hook_input.get("tool_args")
    if isinstance(ta, str):
        try: return json.loads(ta).get("command")
        except: pass
    if isinstance(ta, dict):
        return ta.get("command")
    return None
```

## CLI (__main__.py)

```
hal                                  # Hook mode (default): stdin JSON → evaluate → stdout
hal test "git reset --hard"          # Test a command, human-readable output
hal install                          # Copilot: .github/hooks/hal.json
hal install --claude [--project]     # Claude Code: ~/.claude/settings.json
```

## Install Command

**Copilot** (default) — writes `<repo>/.github/hooks/hal.json`:
```json
{"version": 1, "hooks": {"preToolUse": [{"type": "command", "bash": "/path/to/hal", "powershell": "/path/to/hal", "cwd": ".", "timeoutSec": 30}]}}
```

**Claude Code** (`--claude`) — writes `~/.claude/settings.json`:
```json
{"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "hal"}]}]}}
```

## Config

`~/.config/hal/config.yaml` (optional — zero config by default, all packs enabled):

```yaml
packs: [core.git, core.filesystem, containers.docker, cloud.aws, cloud.azure]
allow: []               # Exact commands to always allow
allow_rules: []         # Rule IDs to disable (e.g. "core.git:push-force")
allow_prefixes: []      # Command prefixes to allow
severity_threshold: high  # Block at this level and above
```

Project-level: `.hal.yaml` in repo root (merged, project wins).

## Error Philosophy: Fail-Open Everywhere

- `shlex.split()` raises → `str.split()`, no masking
- YAML parse error → skip pack, warn stderr
- Config missing → defaults (all packs, no overrides)
- stdin not JSON → exit 0
- Any unhandled exception → exit 0

## Dependencies

- **PyYAML** — only external dep
- Everything else is stdlib (`re`, `json`, `shlex`, `sys`, `argparse`, `pathlib`, `dataclasses`)

## Implementation Order

1. `evaluate.py` — token matching, normalize, extract, sanitize fallback
2. `packs.py` — YAML loading, rule compilation
3. `__main__.py` — CLI + hook I/O
4. YAML packs — port from dcg
5. Tests

## What We Fixed From dcg

1. **The entire false-positive category** — token-level matching means data inside quotes never triggers rules. No sanitizer needed for 90% of rules.
2. **3300-line sanitizer → 30 lines** — only for regex fallback rules.
3. **Pack rules readable by anyone** — `has_all: [reset, --hard]` vs `git\s+(?:\S+\s+)*reset\s+--hard`.
4. **`unless` replaces safe_patterns** — safe overrides built into each rule, not a separate list.
5. **Pack reachability bug** — keyword filter checks ALL enabled packs.
6. **Decision nondeterminism** — ordered lists, not HashSets.
7. **147K LOC → ~400 LOC** — same protection, 99.7% less code.
