"""Tests for hal install command."""

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from hal.__main__ import _install_claude, _install_copilot


class TestInstallCopilot:
    def test_creates_hook_file(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("os.getcwd", return_value=d):
                os.chdir(d)
                _install_copilot("/usr/bin/hal", no_configure=False)
                hook_path = Path(d) / ".github" / "hooks" / "hal.json"
                assert hook_path.exists()
                data = json.loads(hook_path.read_text())
                assert data["command"] == "/usr/bin/hal"
                assert "pre-tool-use" in data["events"]


class TestInstallClaude:
    def test_creates_project_settings(self):
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            _install_claude("/usr/bin/hal", project=True, no_configure=False)
            settings_path = Path(d) / ".claude" / "settings.json"
            assert settings_path.exists()
            data = json.loads(settings_path.read_text())
            assert "hooks" in data
            assert "PreToolUse" in data["hooks"]
            hooks = data["hooks"]["PreToolUse"]
            assert len(hooks) == 1
            assert hooks[0]["command"] == "/usr/bin/hal"

    def test_merges_with_existing(self):
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            settings_dir = Path(d) / ".claude"
            settings_dir.mkdir()
            existing = {
                "hooks": {
                    "PreToolUse": [
                        {"type": "command", "command": "other-tool"}
                    ]
                }
            }
            (settings_dir / "settings.json").write_text(json.dumps(existing))

            _install_claude("/usr/bin/hal", project=True, no_configure=False)
            data = json.loads((settings_dir / "settings.json").read_text())
            hooks = data["hooks"]["PreToolUse"]
            assert len(hooks) == 2  # existing + new
            commands = [h["command"] for h in hooks]
            assert "other-tool" in commands
            assert "/usr/bin/hal" in commands

    def test_updates_existing_hal_hook(self):
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            settings_dir = Path(d) / ".claude"
            settings_dir.mkdir()
            existing = {
                "hooks": {
                    "PreToolUse": [
                        {"type": "command", "command": "/old/path/hal"}
                    ]
                }
            }
            (settings_dir / "settings.json").write_text(json.dumps(existing))

            _install_claude("/new/path/hal", project=True, no_configure=False)
            data = json.loads((settings_dir / "settings.json").read_text())
            hooks = data["hooks"]["PreToolUse"]
            assert len(hooks) == 1
            assert hooks[0]["command"] == "/new/path/hal"

    def test_no_configure_flag(self):
        """--no-configure should not add hooks, just write the file."""
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            _install_claude("/usr/bin/hal", project=True, no_configure=True)
            settings_path = Path(d) / ".claude" / "settings.json"
            assert settings_path.exists()
            data = json.loads(settings_path.read_text())
            # Should be empty or no hooks since no_configure
            assert "hooks" not in data or "PreToolUse" not in data.get("hooks", {})
