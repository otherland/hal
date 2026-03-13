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
        sub.add_parser("install", help="Install hooks for Copilot + Claude Code")

        args = parser.parse_args()

        if args.command == "test":
            _cmd_test(args.cmd)
        elif args.command == "install":
            _cmd_install()
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


def _cmd_install():
    """Install hooks for Copilot and Claude Code. (Placeholder)"""
    print("hal install: not yet implemented", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
