"""Tests for hal.evaluate — normalizer, token engine, extraction, sanitizer."""

import shlex

from hal.evaluate import (
    extract_heredoc,
    extract_inline,
    get_path_args,
    match_rule,
    normalize,
    parse_flags,
    sanitize,
    split_segments,
)
from hal.packs import Rule


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

    def test_flag_with_equals(self):
        flags = parse_flags(["git", "log", "--format=oneline"])
        assert "--format=oneline" in flags
        assert "--format" in flags


# ── match_rule ─────────────────────────────────────────────────────

class TestMatchRule:
    def _rule(self, **kwargs):
        defaults = {"command": "rm", "name": "test"}
        defaults.update(kwargs)
        return Rule(**defaults)

    def test_has_all(self):
        rule = self._rule(has_all=["-rf"])
        tokens = ["rm", "-rf", "/"]
        flags = parse_flags(tokens)
        assert match_rule(tokens, flags, rule) is True
        tokens2 = ["rm", "/"]
        assert match_rule(tokens2, parse_flags(tokens2), rule) is False

    def test_has_any(self):
        rule = self._rule(has_any=["file1", "file2"])
        tokens = ["rm", "file1"]
        assert match_rule(tokens, parse_flags(tokens), rule) is True
        tokens2 = ["rm", "other"]
        assert match_rule(tokens2, parse_flags(tokens2), rule) is False

    def test_flags_contain(self):
        rule = self._rule(flags_contain=["f"])
        tokens = ["rm", "-rf", "/"]
        assert match_rule(tokens, parse_flags(tokens), rule) is True
        tokens2 = ["rm", "/"]
        assert match_rule(tokens2, parse_flags(tokens2), rule) is False

    def test_flags_contain_long(self):
        rule = self._rule(flags_contain=["f"])
        tokens = ["rm", "--force", "/"]
        assert match_rule(tokens, parse_flags(tokens), rule) is True

    def test_unless(self):
        rule = self._rule(command="git", has_all=["push"], unless=["--dry-run"])
        tokens = ["git", "push"]
        assert match_rule(tokens, parse_flags(tokens), rule) is True
        tokens2 = ["git", "push", "--dry-run"]
        assert match_rule(tokens2, parse_flags(tokens2), rule) is False

    def test_command_mismatch(self):
        rule = self._rule(command="rm")
        tokens = ["ls", "-la"]
        assert match_rule(tokens, parse_flags(tokens), rule) is False

    def test_empty_tokens(self):
        rule = self._rule()
        assert match_rule([], set(), rule) is False


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


# ── bd-2de: Extended normalizer tests ─────────────────────────────

class TestNormalizeExtended:
    def test_sudo_g_group(self):
        assert normalize(["sudo", "-g", "wheel", "git", "push"]) == ["git", "push"]

    def test_env_i(self):
        assert normalize(["env", "-i", "git", "push"]) == ["git", "push"]

    def test_abs_path_rm(self):
        assert normalize(["/usr/local/bin/rm", "-rf", "/"]) == ["rm", "-rf", "/"]

    def test_iterative_sudo_env_backslash(self):
        assert normalize(["sudo", "env", "\\git", "push"]) == ["git", "push"]

    def test_command_double_dash(self):
        assert normalize(["command", "--", "git", "push"]) == ["git", "push"]

    def test_unknown_binary_abs_path_unchanged(self):
        assert normalize(["/opt/custom/tool", "arg"]) == ["/opt/custom/tool", "arg"]

    def test_sudo_double_dash(self):
        assert normalize(["sudo", "--", "git", "push"]) == ["git", "push"]

    def test_env_multiple_vars(self):
        assert normalize(["env", "A=1", "B=2", "C=3", "rm", "file"]) == ["rm", "file"]


# ── bd-16f: Extended extraction/segment tests ─────────────────────

class TestExtractInlineExtended:
    def test_python_c(self):
        tokens = shlex.split("python -c 'import os; os.system(\"rm -rf /\")'")
        result = extract_inline(tokens)
        assert result is not None
        assert "os.system" in result

    def test_no_flag_no_match(self):
        tokens = shlex.split("bash script.sh")
        assert extract_inline(tokens) is None


class TestExtractHeredocExtended:
    def test_quoted_marker(self):
        cmd = "bash <<'END'\nrm -rf /\nEND"
        assert extract_heredoc(cmd) == "rm -rf /"

    def test_no_interpreter_ignored(self):
        cmd = "cat <<EOF\nhello world\nEOF"
        assert extract_heredoc(cmd) is None

    def test_heredoc_piped_to_sh(self):
        cmd = "cat <<EOF | sh\necho hello\nEOF"
        assert extract_heredoc(cmd) == "echo hello"


class TestSplitSegmentsExtended:
    def test_double_quoted_pipe(self):
        assert split_segments('echo "a | b" && cmd2') == ['echo "a | b"', "cmd2"]

    def test_multiple_delimiters(self):
        result = split_segments("a | b && c || d ; e")
        assert result == ["a", "b", "c", "d", "e"]


# ── bd-lz4: Sanitizer tests ──────────────────────────────────────

class TestSanitize:
    def test_echo_masks_data(self):
        result = sanitize(["echo", "secret", "data"])
        assert "secret" not in result
        assert "data" not in result
        assert "echo" in result

    def test_git_message_masked(self):
        result = sanitize(["git", "commit", "-m", "my secret message"])
        assert "my secret message" not in result
        assert "-m" in result

    def test_no_masking_for_unknown_cmd(self):
        result = sanitize(["ls", "-la", "/tmp"])
        assert "-la" in result
        assert "/tmp" in result

    def test_empty(self):
        assert sanitize([]) == ""

    def test_curl_data_masked(self):
        result = sanitize(["curl", "-d", "payload", "https://example.com"])
        assert "payload" not in result
        assert "https://example.com" in result
