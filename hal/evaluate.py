"""Command evaluation pipeline — normalize, tokenize, match."""

import fnmatch
import os
import re
import shlex

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
    """Extract all flags from tokens, expanding long→short and combined flags."""
    flags = set()
    for tok in tokens:
        if not tok.startswith("-") or tok == "-" or tok == "--":
            continue
        flags.add(tok)
        # Handle --flag=value: also register the base --flag
        if tok.startswith("--") and "=" in tok:
            base = tok.split("=")[0]
            flags.add(base)
            if base in LONG_FLAG_MAP:
                flags.update(LONG_FLAG_MAP[base])
        # Expand long flags to short equivalents
        elif tok in LONG_FLAG_MAP:
            flags.update(LONG_FLAG_MAP[tok])
        # Expand combined short flags: -rf → -r, -f
        elif not tok.startswith("--") and len(tok) > 2:
            for ch in tok[1:]:
                flags.add(f"-{ch}")
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


def match_rule(tokens: list, flags: set, rule) -> bool:
    """Test whether a single token-based rule matches against tokens and flags.

    Rule is a packs.Rule dataclass with attributes:
      command, has_all, has_any, flags_contain, unless, unless_path, path_is
    """
    if not tokens:
        return False
    if tokens[0] != rule.command:
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

    # unless_path: glob patterns for allowed paths (reject paths with .. traversal)
    if rule.unless_path:
        path_args = get_path_args(tokens)
        for pa in path_args:
            if ".." in pa:
                continue  # traversal — don't let unless_path save it
            if any(fnmatch.fnmatch(pa, pat) for pat in rule.unless_path):
                return False

    # path_is: at least one path argument must exactly match
    if rule.path_is:
        path_args = get_path_args(tokens)
        if not any(pa == rule.path_is for pa in path_args):
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
            if ch in ("|", ";"):
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
