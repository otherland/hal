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
    # Claude Code sends tool_input or hookSpecificInput
    if "hookSpecificInput" in data or "tool_input" in data:
        return CLAUDE
    # Copilot sends toolInput or toolArgs
    if "toolInput" in data or "toolArgs" in data:
        return COPILOT
    # Fallback: check for common Claude patterns
    if "event" in data and isinstance(data.get("event"), str):
        return CLAUDE
    return COPILOT


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

    # Copilot: toolArgs (dict with command)
    tool_args = data.get("toolArgs")
    if isinstance(tool_args, dict):
        return tool_args.get("command") or tool_args.get("input")
    if isinstance(tool_args, str):
        return tool_args

    return None


# ── Output formatting ─────────────────────────────────────────────

def deny_output(protocol: str, rule_id: str, reason: str) -> str:
    """Format a deny/block response for the given protocol."""
    if protocol == COPILOT:
        return json.dumps({
            "continue": False,
            "permissionDecision": "deny",
            "rule": rule_id,
            "message": reason,
        })
    else:
        # Claude Code
        return json.dumps({
            "hookSpecificOutput": {
                "permissionDecision": "deny",
                "rule": rule_id,
                "message": reason,
            }
        })


def ask_output(protocol: str, rule_id: str, reason: str) -> str:
    """Format a warn/ask response for the given protocol."""
    if protocol == COPILOT:
        return json.dumps({
            "continue": True,
            "permissionDecision": "ask",
            "rule": rule_id,
            "message": reason,
        })
    else:
        # Claude Code
        return json.dumps({
            "hookSpecificOutput": {
                "permissionDecision": "ask",
                "rule": rule_id,
                "message": reason,
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
