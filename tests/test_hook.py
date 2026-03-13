"""Tests for hal.hook — Hook I/O protocol."""

import json

from hal.hook import (
    CLAUDE,
    COPILOT,
    allow_output,
    ask_output,
    deny_output,
    detect_protocol,
    extract_command,
)


class TestDetectProtocol:
    def test_claude_hook_specific_input(self):
        data = {"hookSpecificInput": {"command": "rm -rf /"}}
        assert detect_protocol(data) == CLAUDE

    def test_claude_tool_input(self):
        data = {"tool_input": "git push --force"}
        assert detect_protocol(data) == CLAUDE

    def test_copilot_tool_input(self):
        data = {"toolInput": {"command": "rm -rf /"}}
        assert detect_protocol(data) == COPILOT

    def test_copilot_tool_args(self):
        data = {"toolArgs": {"command": "rm -rf /"}}
        assert detect_protocol(data) == COPILOT

    def test_empty_defaults_copilot(self):
        assert detect_protocol({}) == COPILOT


class TestExtractCommand:
    def test_claude_hook_specific(self):
        data = {"hookSpecificInput": {"command": "git push --force"}}
        assert extract_command(data) == "git push --force"

    def test_claude_tool_input_string(self):
        data = {"tool_input": "rm -rf /"}
        assert extract_command(data) == "rm -rf /"

    def test_claude_tool_input_dict(self):
        data = {"tool_input": {"command": "git push"}}
        assert extract_command(data) == "git push"

    def test_copilot_tool_input_string(self):
        data = {"toolInput": "rm -rf /"}
        assert extract_command(data) == "rm -rf /"

    def test_copilot_tool_input_dict(self):
        data = {"toolInput": {"command": "docker system prune -a"}}
        assert extract_command(data) == "docker system prune -a"

    def test_copilot_tool_args_dict(self):
        data = {"toolArgs": {"command": "aws s3 rm --recursive"}}
        assert extract_command(data) == "aws s3 rm --recursive"

    def test_copilot_tool_args_string(self):
        data = {"toolArgs": "git reset --hard"}
        assert extract_command(data) == "git reset --hard"

    def test_empty_returns_none(self):
        assert extract_command({}) is None

    def test_nested_input_field(self):
        data = {"tool_input": {"input": "echo hello"}}
        assert extract_command(data) == "echo hello"


class TestDenyOutput:
    def test_copilot_deny(self):
        result = json.loads(deny_output(COPILOT, "core.git:push-force", "bad push"))
        assert result["continue"] is False
        assert result["permissionDecision"] == "deny"
        assert result["rule"] == "core.git:push-force"

    def test_claude_deny(self):
        result = json.loads(deny_output(CLAUDE, "core.git:push-force", "bad push"))
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert result["hookSpecificOutput"]["rule"] == "core.git:push-force"


class TestAskOutput:
    def test_copilot_ask(self):
        result = json.loads(ask_output(COPILOT, "test:warn", "careful"))
        assert result["continue"] is True
        assert result["permissionDecision"] == "ask"

    def test_claude_ask(self):
        result = json.loads(ask_output(CLAUDE, "test:warn", "careful"))
        assert result["hookSpecificOutput"]["permissionDecision"] == "ask"


class TestAllowOutput:
    def test_allow_empty(self):
        assert allow_output() == ""
