"""Command evaluation pipeline — normalize, tokenize, match."""

from __future__ import annotations

import fnmatch
import os
import re
import shlex
from dataclasses import dataclass, field
from typing import List, Optional

from hal.packs import SEVERITIES

# ── Flag expansion map ──────────────────────────────────────────────
LONG_FLAG_MAP = {
    "--recursive": ["-r", "-R"],
    "--force": ["-f"],
    "--verbose": ["-v"],
    "--quiet": ["-q"],
    "--all": ["-a"],
    "--interactive": ["-i"],
    "--no-preserve-root": ["--no-preserve-root"],
}
SHORT_FLAG_MAP = {
    short: long
    for long, shorts in LONG_FLAG_MAP.items()
    for short in shorts
    if short != long
}

# Binaries whose absolute paths should be stripped to basename
KNOWN_BINARIES = {
    "git", "rm", "mv", "cp", "chmod", "chown", "chgrp", "ln",
    "sudo", "env", "command", "bash", "sh", "zsh", "fish",
    "python", "python3", "node", "ruby", "perl",
    "docker", "kubectl", "aws", "gcloud", "az",
    "curl", "wget", "ssh", "scp", "rsync",
    "kill", "killall", "pkill", "dd", "mkfs", "fdisk",
    "iptables", "systemctl", "journalctl",
}


# ── bd-1ol: Command normalizer ─────────────────────────────────────

def normalize(tokens: list) -> list:
    """Strip sudo, env, backslash prefixes, abs paths for known binaries.

    Iterates until stable so chained prefixes (sudo env git) collapse.
    """
    changed = True
    while changed:
        changed = False

        if not tokens:
            break

        # Strip leading backslash (e.g. \rm → rm)
        if tokens[0].startswith("\\") and len(tokens[0]) > 1:
            tokens[0] = tokens[0][1:]
            changed = True
            continue

        # Strip sudo (handle -u <user> consuming next token, other flags)
        if tokens[0] == "sudo":
            tokens = tokens[1:]
            changed = True
            while tokens:
                if tokens[0] in ("-u", "-g") and len(tokens) > 1:
                    tokens = tokens[2:]  # skip -u/-g and username/group
                elif tokens[0].startswith("-") and tokens[0] != "--":
                    tokens = tokens[1:]
                elif tokens[0] == "--":
                    tokens = tokens[1:]
                    break
                else:
                    break
            continue

        # Strip env (handle VAR=val, -u name, other flags)
        if tokens[0] == "env":
            tokens = tokens[1:]
            changed = True
            while tokens:
                if tokens[0] == "-u" and len(tokens) > 1:
                    tokens = tokens[2:]  # skip -u and var name
                elif "=" in tokens[0] and not tokens[0].startswith("-"):
                    tokens = tokens[1:]  # skip VAR=val
                elif tokens[0].startswith("-") and tokens[0] != "--":
                    tokens = tokens[1:]
                elif tokens[0] == "--":
                    tokens = tokens[1:]
                    break
                else:
                    break
            continue

        # Strip `command` (but NOT command -v/-V which is a lookup)
        if tokens[0] == "command":
            if len(tokens) > 1 and tokens[1] in ("-v", "-V"):
                break  # this is command -v lookup, leave it
            tokens = tokens[1:]
            changed = True
            while tokens and tokens[0].startswith("-"):
                if tokens[0] == "--":
                    tokens = tokens[1:]
                    break
                tokens = tokens[1:]
            continue

        # Strip absolute paths for known binaries
        if "/" in tokens[0]:
            basename = os.path.basename(tokens[0])
            if basename in KNOWN_BINARIES:
                tokens[0] = basename
                changed = True
                continue

    return tokens


# ── bd-38v: Token matching engine ──────────────────────────────────

def parse_flags(tokens: list) -> set:
    """Extract all flags from tokens, aliasing long↔short and splitting combined flags."""
    flags = set()
    for tok in tokens:
        if not tok.startswith("-") or tok == "-" or tok == "--":
            continue
        flags.add(tok)
        # Handle --flag=value: also register the base --flag
        base = tok.split("=")[0]
        flags.add(base)
        flags.update(LONG_FLAG_MAP.get(base, []))
        if base in SHORT_FLAG_MAP:
            flags.add(SHORT_FLAG_MAP[base])
        # Expand combined short flags: -rf → -r, -f (and their long forms)
        if not tok.startswith("--") and len(tok) > 2:
            for ch in tok[1:]:
                short = f"-{ch}"
                flags.add(short)
                if short in SHORT_FLAG_MAP:
                    flags.add(SHORT_FLAG_MAP[short])
    return flags


def get_path_args(tokens: list) -> list:
    """Extract non-flag arguments that look like paths (after the command)."""
    paths = []
    for tok in tokens[1:]:  # skip command itself
        if tok == "--":
            continue
        if tok.startswith("-"):
            continue
        paths.append(tok)
    return paths


def _normalize_path(path: str) -> str:
    """Strip a leading ./ so ./node_modules matches node_modules."""
    return re.sub(r"^\./+", "", path)


def match_rule(tokens: list, flags: set, rule) -> bool:
    """Test whether a single token-based rule matches against tokens and flags.

    Rule is a packs.Rule dataclass with attributes:
      command, has_all, has_any, flags_contain, unless, unless_path, path_is
    """
    if not tokens:
        return False
    if rule.command is not None and tokens[0] != rule.command:
        return False

    all_tokens = set(tokens)
    combined = all_tokens | flags

    # has_all: every listed token must appear
    if rule.has_all and not all(t in all_tokens for t in rule.has_all):
        return False

    # has_any: at least one must appear (check combined for flag variants)
    if rule.has_any and not any(t in combined for t in rule.has_any):
        return False

    # flags_contain: individual flag chars that must all be present
    if rule.flags_contain:
        for fc in rule.flags_contain:
            short = f"-{fc}" if len(fc) == 1 else fc
            if short not in flags:
                return False

    # unless: if any of these tokens appear, rule doesn't match
    if rule.unless and any(t in combined for t in rule.unless):
        return False

    path_args = get_path_args(tokens)

    # unless_path: True rejects '..' traversal; a glob list exempts the
    # command only when every path is safe (rm -rf node_modules / still matches)
    if rule.unless_path is True:
        if any(".." in pa for pa in path_args):
            return True
    elif rule.unless_path and path_args and all(
        ".." not in pa
        and any(fnmatch.fnmatchcase(_normalize_path(pa), pat) for pat in rule.unless_path)
        for pa in path_args
    ):
        return False

    # path_is: at least one path argument must exactly match
    if rule.path_is:
        targets = rule.path_is if isinstance(rule.path_is, list) else [rule.path_is]
        if not any(_normalize_path(pa) in targets for pa in path_args):
            return False

    return True


# ── bd-3w5: Inline/heredoc extraction + segment splitting ──────────

INTERPRETERS = {"bash", "sh", "zsh", "fish", "python", "python3", "ruby", "perl", "node"}
INLINE_FLAGS = {
    "bash": "-c", "sh": "-c", "zsh": "-c", "fish": "-c",
    "python": "-c", "python3": "-c",
    "ruby": "-e", "perl": "-e", "node": "-e",
}


def extract_inline(tokens: list):
    """Detect `bash -c '...'`, `node -e '...'` etc. and return the inline script."""
    if len(tokens) < 3:
        return None
    cmd = os.path.basename(tokens[0]) if "/" in tokens[0] else tokens[0]
    flag = INLINE_FLAGS.get(cmd)
    if not flag:
        return None
    try:
        idx = tokens.index(flag)
        return tokens[idx + 1] if idx + 1 < len(tokens) else None
    except ValueError:
        return None


def extract_heredoc(command: str):
    """Detect heredocs piped to interpreters and return the body."""
    m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", command)
    if not m:
        return None
    delim = m.group(1)
    lines = command.split("\n")
    body, capturing = [], False
    for line in lines:
        if capturing:
            if line.strip() == delim:
                break
            body.append(line)
        elif "<<" in line and delim in line:
            capturing = True
    if not body:
        return None
    # Only evaluate if piped to or invoked by an interpreter
    before = command[:m.start()].strip().split()
    if before and before[0] in INTERPRETERS:
        return "\n".join(body)
    if "|" in command:
        targets = [s.strip().split()[0] for s in command.split("|")[1:] if s.strip()]
        if any(t in INTERPRETERS for t in targets):
            return "\n".join(body)
    return None


def split_segments(command: str) -> list:
    """Split command on |, &&, ||, ; while respecting quotes."""
    segments = []
    current = []
    in_single = False
    in_double = False
    i = 0

    while i < len(command):
        ch = command[i]

        # Handle escape
        if ch == "\\" and i + 1 < len(command) and not in_single:
            current.append(ch)
            current.append(command[i + 1])
            i += 2
            continue

        # Toggle quotes
        if ch == "'" and not in_double:
            in_single = not in_single
            current.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
            i += 1
            continue

        # Only split outside quotes
        if not in_single and not in_double:
            if ch in ("|", "&") and i + 1 < len(command) and command[i + 1] == ch:
                seg = "".join(current).strip()
                if seg:
                    segments.append(seg)
                current = []
                i += 2
                continue
            if ch in ("|", ";", "&"):
                seg = "".join(current).strip()
                if seg:
                    segments.append(seg)
                current = []
                i += 1
                continue

        current.append(ch)
        i += 1

    seg = "".join(current).strip()
    if seg:
        segments.append(seg)

    return segments


# ── Regex fallback sanitizer ────────────────────────────────────────

ALL_ARGS_DATA = {"echo", "printf"}
FLAG_DATA = {
    "git": {"-m", "--message", "--grep"},
    "grep": {"-e", "--regexp"}, "rg": {"-e", "--regexp"},
    "curl": {"-d", "--data", "-H", "--header"},
    "gh": {"-t", "--title", "-b", "--body"},
}


def sanitize(tokens: list) -> str:
    """Mask data tokens for regex fallback rules."""
    if not tokens:
        return ""
    cmd, out, skip = tokens[0], [], False
    for i, tok in enumerate(tokens):
        if skip:
            skip = False
            out.append("_" * len(tok))
            continue
        if i > 0 and cmd in ALL_ARGS_DATA and "$(" not in tok and "`" not in tok:
            out.append("_" * len(tok))
            continue
        if cmd in FLAG_DATA and tok in FLAG_DATA[cmd]:
            skip = True
            out.append(tok)
            continue
        out.append(tok)
    return " ".join(out)


# ── bd-2x0: Evaluation pipeline ──────────────────────────────────

_SEVERITY_ORDER = {name: rank for rank, name in enumerate(SEVERITIES)}
DEFAULT_THRESHOLD = "warn"
_MAX_DEPTH = 1  # max recursion for inline/heredoc extraction


@dataclass
class Decision:
    """Result of evaluating a command."""
    action: str = "allow"       # "allow", "ask" (confirm) or "deny"
    rule_id: str = ""           # which rule matched
    reason: str = ""            # human-readable explanation
    severity: str = ""          # severity from the matching rule
    command: str = ""           # the original command


def evaluate(command: str, packs, config=None, _depth: int = 0) -> Decision:
    """Evaluate a command against loaded packs and config.

    Pipeline: config allow check -> heredoc extraction -> split segments ->
      per-segment: normalize -> tokenize -> keyword pre-filter -> match rules
      (token-based first, regex fallback with sanitize) ->
      inline extraction (recurse once).
    """
    decision = Decision(command=command)

    if not command or not command.strip():
        return decision

    # Config allow-list check: `allow` is exact, `allow_prefixes` is raw prefix
    if config:
        stripped = command.strip()
        if stripped in config.allow:
            return decision
        if any(stripped.startswith(prefix) for prefix in config.allow_prefixes):
            return decision

    threshold = _SEVERITY_ORDER.get(
        config.severity_threshold if config else DEFAULT_THRESHOLD,
        _SEVERITY_ORDER[DEFAULT_THRESHOLD],
    )

    # Heredocs span segments (cat <<EOF | sh), so check the whole command first
    if _depth < _MAX_DEPTH:
        sub = _evaluate_heredoc(command, packs, config, _depth)
        if sub:
            return sub

    for segment in split_segments(command):
        seg_decision = _evaluate_segment(segment, packs, config, threshold, _depth)
        if seg_decision.action != "allow":
            return seg_decision

    return decision


def _evaluate_heredoc(command: str, packs, config, depth: int) -> Optional[Decision]:
    """Evaluate each line of a heredoc fed to an interpreter."""
    heredoc = extract_heredoc(command)
    if not heredoc:
        return None
    for line in heredoc.split("\n"):
        line = line.strip()
        if line:
            sub = evaluate(line, packs, config, _depth=depth + 1)
            if sub.action != "allow":
                return sub
    return None


def _evaluate_segment(
    segment: str, packs, config, threshold: int, depth: int
) -> Decision:
    """Evaluate a single command segment against packs."""
    decision = Decision(command=segment)

    # Tokenize (fail-open to str.split)
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()

    if not tokens:
        return decision

    # Normalize
    tokens = normalize(list(tokens))
    if not tokens:
        return decision

    flags = parse_flags(tokens)
    cmd = tokens[0]

    # Check each pack
    for pack in packs:
        # Keyword pre-filter: skip pack if command doesn't match any keyword
        if pack.keywords and cmd not in pack.keywords:
            continue

        for rule in pack.rules:
            # Skip rules below severity threshold
            rule_sev = _SEVERITY_ORDER.get(rule.severity, 2)
            if rule_sev < threshold:
                continue

            matched = False

            # Token-based matching
            if rule.command is not None or rule.has_all or rule.has_any or rule.flags_contain:
                matched = match_rule(tokens, flags, rule)

            # Regex fallback (if rule has a compiled pattern)
            if not matched and rule.compiled:
                sanitized = sanitize(tokens)
                if rule.compiled.search(sanitized):
                    matched = True
                # Also try unsanitized for patterns that need raw content
                if not matched and rule.compiled.search(segment):
                    matched = True

            if matched:
                # Config allow_rules check
                if config and rule.rule_id in (config.allow_rules or []):
                    continue

                return Decision(
                    action="deny" if rule.severity == "block" else "ask",
                    rule_id=rule.rule_id,
                    reason=rule.reason or rule.name,
                    severity=rule.severity,
                    command=segment,
                )

    # Inline script extraction — recurse once
    if depth < _MAX_DEPTH:
        inline = extract_inline(tokens)
        if inline:
            sub = evaluate(inline, packs, config, _depth=depth + 1)
            if sub.action != "allow":
                return sub

    return decision
