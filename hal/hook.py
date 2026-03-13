"""Hook I/O protocol — detect agent type and format responses."""

from __future__ import annotations

import json
import sys
from typing import Optional


# ── Protocol detection ────────────────────────────────────────────

COPILOT = "copilot"
CLAUDE = "claude"


def detect_protocol(data: dict) -> str:
    """Detect whether input is from Copilot or Claude Code."""
    # Copilot sends event: "pre-tool-use" or toolName like "run_shell_command"
    tool_name = data.get("toolName", "")
    if data.get("event") == "pre-tool-use":
        return COPILOT
    if tool_name in ("run_shell_command", "run-shell-command"):
        return COPILOT
    if "toolInput" in data or "toolArgs" in data:
        return COPILOT
    # Everything else is Claude Code
    return CLAUDE


def extract_command(data: dict) -> Optional[str]:
    """Extract the command string from hook input JSON.

    Handles various input shapes:
      - tool_input / toolInput / toolArgs as string or dict
      - hookSpecificInput.command
      - Nested command/input fields
    """
    # Claude Code: hookSpecificInput.command or tool_input
    hook_input = data.get("hookSpecificInput", {})
    if isinstance(hook_input, dict) and "command" in hook_input:
        return hook_input["command"]

    # Claude Code: tool_input (string or dict with command)
    tool_input = data.get("tool_input")
    if isinstance(tool_input, str):
        return tool_input
    if isinstance(tool_input, dict):
        return tool_input.get("command") or tool_input.get("input")

    # Copilot: toolInput (string or dict)
    tool_input = data.get("toolInput")
    if isinstance(tool_input, str):
        return tool_input
    if isinstance(tool_input, dict):
        return tool_input.get("command") or tool_input.get("input")

    # Copilot: toolArgs (dict with command, or JSON string)
    tool_args = data.get("toolArgs")
    if isinstance(tool_args, str):
        try:
            tool_args = json.loads(tool_args)
        except (json.JSONDecodeError, ValueError):
            return tool_args
    if isinstance(tool_args, dict):
        return tool_args.get("command") or tool_args.get("input")

    return None


# ── Output formatting ─────────────────────────────────────────────

def deny_output(protocol: str, rule_id: str, reason: str) -> str:
    """Format a deny/block response for the given protocol."""
    msg = f"BLOCKED [{rule_id}]: {reason}"
    if protocol == COPILOT:
        return json.dumps({
            "continue": False,
            "stopReason": msg,
            "permissionDecision": "deny",
            "permissionDecisionReason": msg,
        })
    else:
        # Claude Code
        return json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": msg,
            }
        })


def ask_output(protocol: str, rule_id: str, reason: str) -> str:
    """Format a warn/ask response for the given protocol."""
    msg = f"WARNING [{rule_id}]: {reason}"
    if protocol == COPILOT:
        return json.dumps({
            "continue": True,
            "stopReason": msg,
            "permissionDecision": "ask",
            "permissionDecisionReason": msg,
        })
    else:
        # Claude Code
        return json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": msg,
            }
        })


def allow_output() -> str:
    """Format an allow response — empty stdout + exit 0."""
    return ""


def read_input() -> Optional[dict]:
    """Read JSON input from stdin. Returns None on error (fail-open)."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return None
        return json.loads(raw)
    except (json.JSONDecodeError, IOError):
        return None
