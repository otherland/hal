"""Tests for hal.evaluate — normalizer, token engine, extraction, sanitizer."""

import shlex

from hal.evaluate import (
    Decision,
    evaluate,
    extract_heredoc,
    extract_inline,
    get_path_args,
    match_rule,
    normalize,
    parse_flags,
    sanitize,
    split_segments,
)
from hal.config import Config
from hal.packs import Pack, Rule, load_packs


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


# ── bd-2x0: Evaluation pipeline tests ────────────────────────────

class TestEvaluate:
    def _git_pack(self):
        """Minimal git pack for testing."""
        return Pack(
            id="core.git",
            name="core.git",
            keywords=["git"],
            rules=[
                Rule(
                    name="push-force",
                    command="git",
                    has_all=["push"],
                    flags_contain=["f"],
                    unless=["--force-with-lease"],
                    severity="block",
                    rule_id="core.git:push-force",
                    reason="git push --force can overwrite remote history",
                ),
                Rule(
                    name="reset-hard",
                    command="git",
                    has_all=["reset"],
                    flags_contain=["--hard"],
                    severity="block",
                    rule_id="core.git:reset-hard",
                    reason="git reset --hard discards uncommitted changes",
                ),
            ],
        )

    def _rm_pack(self):
        """Minimal filesystem pack for testing."""
        return Pack(
            id="core.fs",
            name="core.fs",
            keywords=["rm"],
            rules=[
                Rule(
                    name="rm-rf",
                    command="rm",
                    has_all=["rm"],
                    flags_contain=["r", "f"],
                    severity="block",
                    rule_id="core.fs:rm-rf",
                    reason="rm -rf with both recursive and force flags",
                ),
            ],
        )

    def test_safe_command_allowed(self):
        d = evaluate("git status", [self._git_pack()])
        assert d.action == "allow"

    def test_dangerous_command_blocked(self):
        d = evaluate("git push --force", [self._git_pack()])
        assert d.action == "block"
        assert "push-force" in d.rule_id

    def test_unless_exemption(self):
        d = evaluate("git push --force-with-lease", [self._git_pack()])
        assert d.action == "allow"

    def test_empty_command(self):
        d = evaluate("", [self._git_pack()])
        assert d.action == "allow"

    def test_chained_commands_blocked(self):
        d = evaluate("echo hello && git push --force", [self._git_pack()])
        assert d.action == "block"

    def test_sudo_normalized(self):
        d = evaluate("sudo git push --force", [self._git_pack()])
        assert d.action == "block"

    def test_rm_rf_blocked(self):
        d = evaluate("rm -rf /", [self._rm_pack()])
        assert d.action == "block"

    def test_config_allow_list(self):
        config = Config(allow=["git push --force"])
        d = evaluate("git push --force", [self._git_pack()], config)
        assert d.action == "allow"

    def test_config_allow_rules(self):
        config = Config(allow_rules=["core.git:push-force"])
        d = evaluate("git push --force", [self._git_pack()], config)
        assert d.action == "allow"

    def test_config_allow_prefixes(self):
        config = Config(allow_prefixes=["git push"])
        d = evaluate("git push --force", [self._git_pack()], config)
        assert d.action == "allow"

    def test_inline_script_blocked(self):
        d = evaluate("bash -c 'rm -rf /'", [self._rm_pack()])
        assert d.action == "block"

    def test_with_real_packs(self):
        """Integration test with actual YAML packs."""
        packs = load_packs()
        d = evaluate("git push --force origin main", packs)
        assert d.action == "block"

        d2 = evaluate("git status", packs)
        assert d2.action == "allow"

    def test_severity_threshold(self):
        """Commands below severity threshold should be allowed."""
        config = Config(severity_threshold="block")
        pack = Pack(
            id="test", name="test", keywords=[],
            rules=[Rule(
                name="warn-only", command="git", has_all=["push"],
                severity="warn", rule_id="test:warn-only",
            )],
        )
        d = evaluate("git push", [pack], config)
        assert d.action == "allow"  # warn < block threshold

    def test_pipe_segment_blocked(self):
        d = evaluate("cat /etc/passwd | rm -rf /", [self._rm_pack()])
        assert d.action == "block"

    def test_semicolon_segment_blocked(self):
        d = evaluate("echo ok; rm -rf /", [self._rm_pack()])
        assert d.action == "block"

    def test_env_normalized(self):
        d = evaluate("env VAR=1 git push --force", [self._git_pack()])
        assert d.action == "block"

    def test_backslash_normalized(self):
        """Backslash-prefixed commands should still be caught."""
        packs = load_packs()
        d = evaluate("\\git push --force", packs)
        assert d.action == "block"

    def test_abs_path_normalized(self):
        packs = load_packs()
        d = evaluate("/usr/bin/git push --force", packs)
        assert d.action == "block"


# ── bd-32z: Comprehensive pipeline tests with real packs ─────────

class TestEvaluateWithRealPacks:
    """Test evaluate() against all built-in YAML packs."""

    @classmethod
    def setup_class(cls):
        cls.packs = load_packs()

    # -- Git pack --
    def test_git_reset_hard_blocked(self):
        assert evaluate("git reset --hard HEAD~1", self.packs).action == "block"

    def test_git_reset_soft_allowed(self):
        assert evaluate("git reset --soft HEAD~1", self.packs).action == "allow"

    def test_git_push_force_blocked(self):
        assert evaluate("git push --force origin main", self.packs).action == "block"

    def test_git_push_force_with_lease_allowed(self):
        assert evaluate("git push --force-with-lease origin main", self.packs).action == "allow"

    def test_git_clean_f_blocked(self):
        assert evaluate("git clean -f", self.packs).action == "block"

    def test_git_clean_dry_run_allowed(self):
        assert evaluate("git clean -f -n", self.packs).action == "allow"

    def test_git_stash_clear_blocked(self):
        assert evaluate("git stash clear", self.packs).action == "block"

    def test_git_branch_D_warn_below_threshold(self):
        # branch -D is severity=warn, default threshold is high, so it's allowed
        assert evaluate("git branch -D feature", self.packs).action == "allow"

    def test_git_branch_D_blocked_low_threshold(self):
        config = Config(severity_threshold="warn")
        assert evaluate("git branch -D feature", self.packs, config).action == "block"

    def test_git_branch_d_allowed(self):
        assert evaluate("git branch -d feature", self.packs).action == "allow"

    def test_git_status_allowed(self):
        assert evaluate("git status", self.packs).action == "allow"

    def test_git_commit_allowed(self):
        assert evaluate("git commit -m 'fix bug'", self.packs).action == "allow"

    def test_git_pull_allowed(self):
        assert evaluate("git pull origin main", self.packs).action == "allow"

    # -- Filesystem pack --
    def test_rm_rf_blocked(self):
        assert evaluate("rm -rf /", self.packs).action == "block"

    def test_rm_rf_combined_blocked(self):
        assert evaluate("rm -rf /var/data", self.packs).action == "block"

    def test_rm_single_file_allowed(self):
        assert evaluate("rm file.txt", self.packs).action == "allow"

    def test_chmod_777_blocked(self):
        assert evaluate("chmod 777 /etc/passwd", self.packs).action == "block"

    def test_chmod_644_allowed(self):
        assert evaluate("chmod 644 file.txt", self.packs).action == "allow"

    def test_mkfs_blocked(self):
        # mkfs (exact token) is blocked; mkfs.ext4 is a different token
        assert evaluate("mkfs /dev/sda1", self.packs).action == "block"

    def test_mkfs_ext4_not_matched(self):
        # mkfs.ext4 doesn't match has_all: [mkfs] — token is "mkfs.ext4"
        assert evaluate("mkfs.ext4 /dev/sda1", self.packs).action == "allow"

    # -- Docker pack --
    def test_docker_system_prune_a_blocked(self):
        assert evaluate("docker system prune -a", self.packs).action == "block"

    def test_docker_volume_prune_blocked(self):
        assert evaluate("docker volume prune", self.packs).action == "block"

    def test_docker_ps_allowed(self):
        assert evaluate("docker ps", self.packs).action == "allow"

    def test_docker_build_allowed(self):
        assert evaluate("docker build -t myapp .", self.packs).action == "allow"

    # -- AWS pack --
    def test_aws_s3_rm_recursive_blocked(self):
        assert evaluate("aws s3 rm s3://bucket --recursive", self.packs).action == "block"

    def test_aws_ec2_terminate_blocked(self):
        assert evaluate("aws ec2 terminate-instances --instance-ids i-123", self.packs).action == "block"

    def test_aws_s3_ls_allowed(self):
        assert evaluate("aws s3 ls", self.packs).action == "allow"

    # -- Azure pack --
    def test_az_group_delete_blocked(self):
        assert evaluate("az group delete --name mygroup", self.packs).action == "block"

    def test_az_vm_delete_blocked(self):
        assert evaluate("az vm delete --name myvm", self.packs).action == "block"

    def test_az_vm_list_allowed(self):
        assert evaluate("az vm list", self.packs).action == "allow"

    # -- Normalization in pipeline --
    def test_sudo_git_push_force(self):
        assert evaluate("sudo git push --force", self.packs).action == "block"

    def test_env_rm_rf(self):
        assert evaluate("env VAR=1 rm -rf /", self.packs).action == "block"

    def test_abs_path_rm_rf(self):
        assert evaluate("/usr/bin/rm -rf /", self.packs).action == "block"

    # -- Segment splitting --
    def test_safe_then_dangerous(self):
        assert evaluate("echo hello && git push --force", self.packs).action == "block"

    def test_pipe_to_dangerous(self):
        assert evaluate("cat file | rm -rf /", self.packs).action == "block"

    # -- Inline extraction --
    def test_bash_c_rm_rf(self):
        assert evaluate("bash -c 'rm -rf /'", self.packs).action == "block"

    def test_bash_c_safe(self):
        assert evaluate("bash -c 'echo hello'", self.packs).action == "allow"

    # -- Safe commands --
    def test_ls_allowed(self):
        assert evaluate("ls -la", self.packs).action == "allow"

    def test_cat_allowed(self):
        assert evaluate("cat /etc/hosts", self.packs).action == "allow"

    def test_echo_allowed(self):
        assert evaluate("echo hello world", self.packs).action == "allow"

    def test_npm_install_allowed(self):
        assert evaluate("npm install express", self.packs).action == "allow"

    def test_python_allowed(self):
        assert evaluate("python3 script.py", self.packs).action == "allow"
