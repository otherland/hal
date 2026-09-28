"""Read-only checks for Copilot hook installation and trust."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def repo_root() -> Path:
    """Return the Git repository root, or the current directory."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip()).resolve()
    except (OSError, subprocess.CalledProcessError):
        return Path.cwd().resolve()


def _trusted_folder(root: Path) -> tuple[bool, str]:
    if os.environ.get("GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS", "").lower() == "true":
        return True, "GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS is enabled"

    home = Path(os.environ.get("COPILOT_HOME", Path.home() / ".copilot"))
    config_path = home / "config.json"
    try:
        config = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False, f"trustedFolders not found in {config_path}"

    for value in config.get("trustedFolders", []):
        try:
            trusted = Path(value).expanduser().resolve()
            root.relative_to(trusted)
            return True, f"trusted by {trusted}"
        except (TypeError, ValueError, OSError):
            continue
    return False, f"{root} is not in {config_path}'s trustedFolders"


def run() -> int:
    """Print hook status and return zero only when configured and trusted."""
    root = repo_root()
    hook_path = root / ".github" / "hooks" / "hal.json"
    print("HAL doctor")
    print(f"\nRepository: {root}")

    if not hook_path.exists():
        print("✗ hook file: missing (.github/hooks/hal.json)")
        print("\nStatus: not installed")
        return 1

    try:
        data = json.loads(hook_path.read_text())
        entries = data["hooks"]["preToolUse"]
        if data.get("version") != 1 or not isinstance(entries, list) or not entries:
            raise ValueError("missing version 1 preToolUse hook")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"✗ hook file: invalid ({exc})")
        print("\nStatus: invalid")
        return 1

    print("✓ hook file: .github/hooks/hal.json")
    print("✓ preToolUse configured")

    executable = shutil.which("hal")
    configured = [
        entry.get("bash") or entry.get("exec")
        for entry in entries
        if isinstance(entry, dict)
    ]
    if executable and executable in configured:
        print(f"✓ command: {executable}")
    else:
        print(f"! command: {configured[0] if configured else 'missing'}")

    trusted, reason = _trusted_folder(root)
    if trusted:
        print(f"✓ repository trust: {reason}")
        print("\nStatus: configured and trusted")
        return 0

    print(f"! repository trust: {reason}")
    print("\nStatus: configured-but-untrusted")
    print("Action: trust this repository before unattended Copilot use")
    return 1
