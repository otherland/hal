"""Tests for hal.evaluate — normalizer, token engine, extraction."""

import shlex

from hal.evaluate import (
    extract_heredoc,
    extract_inline,
    get_path_args,
    match_rule,
    normalize,
    parse_flags,
    split_segments,
)


# ── normalize ──────────────────────────────────────────────────────

class TestNormalize:
    def test_strip_sudo(self):
        assert normalize(["sudo", "rm", "-rf", "/"]) == ["rm", "-rf", "/"]

    def test_strip_sudo_u(self):
        assert normalize(["sudo", "-u", "root", "git", "push"]) == ["git", "push"]

    def test_strip_env_vars(self):
        assert normalize(["env", "VAR=1", "VAR2=2", "git", "push"]) == ["git", "push"]

    def test_strip_env_u(self):
        assert normalize(["env", "-u", "FOO", "git", "push"]) == ["git", "push"]

    def test_strip_backslash(self):
        assert normalize(["\\rm", "-rf", "/"]) == ["rm", "-rf", "/"]

    def test_strip_absolute_path(self):
        assert normalize(["/usr/bin/git", "push"]) == ["git", "push"]

    def test_chained_sudo_env(self):
        assert normalize(["sudo", "env", "VAR=1", "git", "push"]) == ["git", "push"]

    def test_command_passthrough(self):
        assert normalize(["command", "git", "push"]) == ["git", "push"]

    def test_command_v_preserved(self):
        assert normalize(["command", "-v", "git"]) == ["command", "-v", "git"]

    def test_empty(self):
        assert normalize([]) == []


# ── parse_flags ────────────────────────────────────────────────────

class TestParseFlags:
    def test_basic(self):
        flags = parse_flags(["rm", "-rf", "/"])
        assert "-r" in flags
        assert "-f" in flags
        assert "-rf" in flags

    def test_long_flag_expansion(self):
        flags = parse_flags(["rm", "--recursive", "--force", "/"])
        assert "-r" in flags or "-R" in flags
        assert "-f" in flags
        assert "--recursive" in flags
        assert "--force" in flags

    def test_no_flags(self):
        assert parse_flags(["ls"]) == set()


# ── match_rule ─────────────────────────────────────────────────────

class TestMatchRule:
    def test_has_all(self):
        rule = {"has_all": ["rm", "-rf"]}
        assert match_rule(rule, ["rm", "-rf", "/"]) is True
        assert match_rule(rule, ["rm", "/"]) is False

    def test_has_any(self):
        rule = {"has_any": ["rm", "del"]}
        assert match_rule(rule, ["rm", "file"]) is True
        assert match_rule(rule, ["ls"]) is False

    def test_flags_contain(self):
        rule = {"flags_contain": ["-f"]}
        assert match_rule(rule, ["rm", "-rf", "/"]) is True
        assert match_rule(rule, ["rm", "/"]) is False

    def test_flags_contain_long(self):
        rule = {"flags_contain": ["-f"]}
        assert match_rule(rule, ["rm", "--force", "/"]) is True

    def test_unless(self):
        rule = {"has_all": ["git", "push"], "unless": ["--dry-run"]}
        assert match_rule(rule, ["git", "push"]) is True
        assert match_rule(rule, ["git", "push", "--dry-run"]) is False

    def test_unless_path(self):
        rule = {"has_all": ["rm"], "unless_path": True}
        assert match_rule(rule, ["rm", "../etc/passwd"]) is False
        assert match_rule(rule, ["rm", "file.txt"]) is True

    def test_path_is(self):
        rule = {"has_all": ["rm"], "path_is": ["/"]}
        assert match_rule(rule, ["rm", "/"]) is True
        assert match_rule(rule, ["rm", "/tmp"]) is False

    def test_empty_tokens(self):
        assert match_rule({"has_all": ["rm"]}, []) is False


# ── extract_inline ─────────────────────────────────────────────────

class TestExtractInline:
    def test_bash_c(self):
        tokens = shlex.split("bash -c 'rm -rf /'")
        assert extract_inline(tokens) == "rm -rf /"

    def test_node_e(self):
        tokens = shlex.split("node -e 'process.exit(1)'")
        assert extract_inline(tokens) == "process.exit(1)"

    def test_no_inline(self):
        tokens = shlex.split("git push")
        assert extract_inline(tokens) is None


# ── extract_heredoc ────────────────────────────────────────────────

class TestExtractHeredoc:
    def test_basic_heredoc(self):
        cmd = "bash <<EOF\nrm -rf /\nEOF"
        assert extract_heredoc(cmd) == "rm -rf /"

    def test_no_heredoc(self):
        assert extract_heredoc("git push") is None


# ── split_segments ─────────────────────────────────────────────────

class TestSplitSegments:
    def test_pipe(self):
        assert split_segments("cat file | grep foo") == ["cat file", "grep foo"]

    def test_and(self):
        assert split_segments("cd /tmp && rm -rf *") == ["cd /tmp", "rm -rf *"]

    def test_or(self):
        assert split_segments("cmd1 || cmd2") == ["cmd1", "cmd2"]

    def test_semicolon(self):
        assert split_segments("cmd1; cmd2") == ["cmd1", "cmd2"]

    def test_quoted_pipe(self):
        assert split_segments("echo 'a | b' && cmd2") == ["echo 'a | b'", "cmd2"]

    def test_single_command(self):
        assert split_segments("ls -la") == ["ls -la"]
