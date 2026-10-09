"""`hal doctor` — check the Copilot hook install, repository trust, and packs."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def repo_root() -> str:
    """Top level of the current Git repository."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as e:
        raise RuntimeError("Copilot installation must be run inside a Git repository") from e


def _trust(root: str, config_file: Path) -> str:
    try:
        config = json.loads(config_file.read_text())
        folders = config.get("trustedFolders") if isinstance(config, dict) else None
        folders = [f for f in folders if isinstance(f, str)] if isinstance(folders, list) else []
    except (OSError, ValueError):
        return f"trustedFolders not found in {config_file}"
    for folder in folders:
        resolved = os.path.abspath(folder)
        if root == resolved or root.startswith(resolved + os.sep):
            return f"trusted by {config_file}"
    return f"{root} is not in {config_file}'s trustedFolders"


def doctor(diagnostics=()) -> int:
    """Print a health report and return the exit code (0 when all is well)."""
    root = repo_root()
    hook_file = Path(root) / ".github" / "hooks" / "hal.json"
    print("HAL doctor\n")
    print(f"Repository: {root}")
    for d in diagnostics:
        print(f"! pack: {d.file}: {d.message}")

    if not hook_file.exists():
        print("✗ hook file: missing (.github/hooks/hal.json)\n\nStatus: not installed")
        return 1
    try:
        hook = json.loads(hook_file.read_text())
        pre_tool_use = hook.get("hooks", {}).get("preToolUse")
        if hook.get("version") != 1 or not isinstance(pre_tool_use, list) or not pre_tool_use:
            raise ValueError("missing version 1 preToolUse hook")
    except (OSError, ValueError, AttributeError) as e:
        print(f"✗ hook file: invalid ({e})\n\nStatus: invalid")
        return 1
    print("✓ hook file: .github/hooks/hal.json\n✓ preToolUse configured")

    home = os.environ.get("COPILOT_HOME") or os.path.join(os.path.expanduser("~"), ".copilot")
    override = os.environ.get("GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS", "").lower() == "true"
    reason = (
        "GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS is enabled"
        if override else _trust(root, Path(home) / "config.json")
    )
    if override or reason.startswith("trusted by"):
        if diagnostics:
            print("\nStatus: configured with invalid pack rules")
            return 1
        print(f"✓ repository trust: {reason}\n\nStatus: configured and trusted")
        return 0
    status = "configured-but-untrusted" + (" with invalid pack rules" if diagnostics else "")
    print(f"! repository trust: {reason}\n\nStatus: {status}\n"
          "Action: trust this repository before unattended Copilot use")
    return 1
