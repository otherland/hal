"""CLI entry point for HAL."""

from __future__ import annotations

import argparse
import sys


def main():
    """Main entry point — dispatches to hook, test, or install mode."""
    try:
        parser = argparse.ArgumentParser(
            prog="hal",
            description="HAL — Harmful Action Limiter",
        )
        sub = parser.add_subparsers(dest="command")

        # hal test "command"
        test_p = sub.add_parser("test", help="Test a command against rules")
        test_p.add_argument("cmd", help="Command string to evaluate")

        # hal install
        install_p = sub.add_parser("install", help="Install hooks for Copilot + Claude Code")
        install_p.add_argument("--claude", action="store_true", help="Install Claude Code hook")
        install_p.add_argument("--project", action="store_true", help="Use project-level settings (with --claude)")
        install_p.add_argument("--no-configure", action="store_true", help="Only update binary path")

        args = parser.parse_args()

        if args.command == "test":
            _cmd_test(args.cmd)
        elif args.command == "install":
            _cmd_install(
                claude=args.claude,
                project=args.project,
                no_configure=args.no_configure,
            )
        else:
            # Default: hook mode — read JSON from stdin, evaluate, respond
            _cmd_hook()

    except Exception:
        # Fail-open: any error = allow
        sys.exit(0)


def _cmd_hook():
    """Hook mode: read JSON from stdin, evaluate command, output decision."""
    from hal.config import load_config
    from hal.evaluate import evaluate
    from hal.hook import (
        allow_output,
        ask_output,
        deny_output,
        detect_protocol,
        extract_command,
        read_input,
    )
    from hal.packs import load_packs

    data = read_input()
    if data is None:
        sys.exit(0)  # fail-open: no input = allow

    command = extract_command(data)
    if not command:
        sys.exit(0)  # fail-open: no command = allow

    protocol = detect_protocol(data)
    config = load_config()
    packs = load_packs(config.pack_dirs if config.pack_dirs else None)

    decision = evaluate(command, packs, config)

    if decision.action == "block":
        if decision.severity in ("warn", "medium", "low", "info"):
            print(ask_output(protocol, decision.rule_id, decision.reason))
        else:
            print(deny_output(protocol, decision.rule_id, decision.reason))
        sys.exit(0)

    # Allow — empty stdout, exit 0
    output = allow_output()
    if output:
        print(output)
    sys.exit(0)


def _cmd_test(command: str):
    """Test mode: evaluate a command and print human-readable output."""
    from hal.config import load_config
    from hal.evaluate import evaluate
    from hal.packs import load_packs

    config = load_config()
    packs = load_packs(config.pack_dirs if config.pack_dirs else None)

    decision = evaluate(command, packs, config)

    if decision.action == "block":
        # Red for block
        print(f"\033[91m✗ BLOCKED\033[0m  {command}")
        print(f"  rule:     {decision.rule_id}")
        print(f"  reason:   {decision.reason}")
        print(f"  severity: {decision.severity}")
        sys.exit(1)
    else:
        # Green for allow
        print(f"\033[92m✓ ALLOWED\033[0m  {command}")
        sys.exit(0)


def _cmd_install(claude: bool = False, project: bool = False, no_configure: bool = False):
    """Install hooks for Copilot and/or Claude Code."""
    import json
    import shutil
    from pathlib import Path

    hal_path = shutil.which("hal") or sys.executable + " -m hal"

    if claude:
        _install_claude(hal_path, project, no_configure)
    else:
        _install_copilot(hal_path, no_configure)


def _install_claude(hal_path: str, project: bool, no_configure: bool):
    """Install Claude Code hook into settings.json."""
    import json
    from pathlib import Path

    if project:
        settings_path = Path(".claude") / "settings.json"
    else:
        settings_path = Path.home() / ".claude" / "settings.json"

    settings_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing settings
    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, OSError):
            settings = {}

    if not no_configure:
        # Add/merge hook
        hooks = settings.setdefault("hooks", {})
        pre_tool = hooks.setdefault("PreToolUse", [])

        # Correct Claude Code structure: matcher + hooks array
        hal_entry = {
            "matcher": "Bash",
            "hooks": [
                {"type": "command", "command": hal_path}
            ],
        }

        # Check if hal hook already exists (nested structure)
        existing = [
            h for h in pre_tool
            if isinstance(h, dict)
            and any("hal" in hook.get("command", "") for hook in h.get("hooks", []) if isinstance(hook, dict))
        ]
        if existing:
            for h in existing:
                h["hooks"] = [{"type": "command", "command": hal_path}]
        else:
            pre_tool.append(hal_entry)

    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"hal: installed Claude Code hook at {settings_path}")


def _install_copilot(hal_path: str, no_configure: bool):
    """Install Copilot hook into .github/hooks/."""
    import json
    from pathlib import Path

    hooks_dir = Path(".github") / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "hal.json"

    hook_config = {
        "version": 1,
        "hooks": {
            "preToolUse": [
                {
                    "type": "command",
                    "bash": hal_path,
                    "powershell": hal_path,
                    "cwd": ".",
                    "timeoutSec": 30,
                }
            ],
        },
    }

    hook_path.write_text(json.dumps(hook_config, indent=2) + "\n")
    print(f"hal: installed Copilot hook at {hook_path}")


if __name__ == "__main__":
    main()
