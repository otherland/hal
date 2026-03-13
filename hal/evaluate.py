"""Command evaluation pipeline — normalize, tokenize, match."""

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

def normalize(tokens: list[str]) -> list[str]:
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
            # consume sudo flags
            while tokens:
                if tokens[0] == "-u" and len(tokens) > 1:
                    tokens = tokens[2:]  # skip -u and username
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
            # consume command flags (e.g. -p)
            while tokens and tokens[0].startswith("-") and tokens[0] != "--":
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

def parse_flags(tokens: list[str]) -> set[str]:
    """Extract all flags from tokens, expanding long flags to short equivalents."""
    flags = set()
    for tok in tokens:
        if tok.startswith("-") and tok != "-" and tok != "--":
            flags.add(tok)
            # Expand long flags
            if tok in LONG_FLAG_MAP:
                flags.update(LONG_FLAG_MAP[tok])
            # Expand combined short flags: -rf → -r, -f
            elif tok.startswith("-") and not tok.startswith("--") and len(tok) > 2:
                for ch in tok[1:]:
                    flags.add(f"-{ch}")
    return flags


def get_path_args(tokens: list[str]) -> list[str]:
    """Extract non-flag arguments that look like paths (after the command)."""
    paths = []
    for tok in tokens[1:]:  # skip command itself
        if tok == "--":
            continue
        if tok.startswith("-"):
            continue
        paths.append(tok)
    return paths


def match_rule(rule: dict, tokens: list[str]) -> bool:
    """Test whether a single rule matches the tokenized command.

    Supported rule keys:
      has_all:      list of tokens that must ALL appear
      has_any:      list of tokens where at least ONE must appear
      flags_contain: list of flags (short or long) that must ALL be present
      unless:       list of tokens — if ANY appears, rule does NOT match
      unless_path:  if true, reject paths with '..' (traversal detection)
      path_is:      list of exact path values — at least one path arg must match
      regex:        compiled regex pattern to test against joined command
    """
    if not tokens:
        return False

    # has_all: every listed token must appear
    if "has_all" in rule:
        for required in rule["has_all"]:
            if required not in tokens:
                return False

    # has_any: at least one listed token must appear
    if "has_any" in rule:
        if not any(t in tokens for t in rule["has_any"]):
            return False

    # flags_contain: all listed flags must be present (with expansion)
    if "flags_contain" in rule:
        flags = parse_flags(tokens)
        for required_flag in rule["flags_contain"]:
            if required_flag not in flags:
                # Check if the required flag is a short flag that might be in a combo
                # parse_flags already expands combos, so just check
                return False

    # unless: if any of these tokens appear, rule doesn't match
    if "unless" in rule:
        for excluded in rule["unless"]:
            if excluded in tokens:
                return False

    # unless_path: reject if any path arg contains '..'
    if rule.get("unless_path"):
        paths = get_path_args(tokens)
        for p in paths:
            if ".." in p:
                return False

    # path_is: at least one path argument must exactly match
    if "path_is" in rule:
        paths = get_path_args(tokens)
        if not any(p in rule["path_is"] for p in paths):
            return False

    # regex: compiled pattern must match the reconstructed command
    if "regex" in rule:
        cmd_str = " ".join(tokens)
        if not rule["regex"].search(cmd_str):
            return False

    return True


# ── bd-3w5: Inline/heredoc extraction + segment splitting ──────────

_INLINE_INTERPRETERS = {"bash", "sh", "zsh", "fish", "python", "python3", "ruby", "perl", "node"}
_INLINE_FLAGS = {"-c", "-e"}


def extract_inline(tokens: list[str]) -> str | None:
    """Detect `bash -c '...'`, `node -e '...'` etc. and return the inline script."""
    for i, tok in enumerate(tokens):
        basename = os.path.basename(tok) if "/" in tok else tok
        if basename in _INLINE_INTERPRETERS:
            # Look for -c or -e followed by the script
            for j in range(i + 1, len(tokens)):
                if tokens[j] in _INLINE_FLAGS and j + 1 < len(tokens):
                    return tokens[j + 1]
    return None


def extract_heredoc(command: str) -> str | None:
    """Detect heredocs piped to interpreters and return the body.

    Handles patterns like:
      cat <<EOF | bash
      bash <<EOF
      python3 << 'MARKER'
    """
    m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", command)
    if not m:
        return None
    marker = m.group(1)
    # Find the body between the marker lines
    pattern = rf"<<-?\s*['\"]?{re.escape(marker)}['\"]?\s*\n(.*?)\n\s*{re.escape(marker)}\b"
    body_match = re.search(pattern, command, re.DOTALL)
    if body_match:
        return body_match.group(1)
    return None


def split_segments(command: str) -> list[str]:
    """Split command on |, &&, ||, ; while respecting quotes.

    Returns list of individual command strings.
    """
    segments = []
    current: list[str] = []
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
            # Check for ||, &&
            if ch in ("|", "&") and i + 1 < len(command) and command[i + 1] == ch:
                seg = "".join(current).strip()
                if seg:
                    segments.append(seg)
                current = []
                i += 2
                continue
            # Check for single | (pipe) or ;
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
