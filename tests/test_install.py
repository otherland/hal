"""Tests for hal install command."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from hal.__main__ import _install_claude, _install_copilot


def _hal_commands(entries):
    return [hook["command"] for entry in entries for hook in entry["hooks"]]


class TestInstallCopilot:
    def test_creates_hook_file_at_repo_root(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "--quiet"], cwd=d, check=True)
            sub = Path(d) / "sub"
            sub.mkdir()
            os.chdir(sub)
            _install_copilot("/usr/bin/hal", no_configure=False)
            hook_path = Path(d) / ".github" / "hooks" / "hal.json"
            data = json.loads(hook_path.read_text())
            assert data["version"] == 1
            assert data["hooks"]["preToolUse"][0]["bash"] == "/usr/bin/hal"
            assert data["hooks"]["preToolUse"][0]["powershell"] == "/usr/bin/hal"


class TestInstallClaude:
    def test_creates_project_settings(self):
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            _install_claude("/usr/bin/hal", project=True, no_configure=False)
            data = json.loads((Path(d) / ".claude" / "settings.json").read_text())
            entries = data["hooks"]["PreToolUse"]
            assert len(entries) == 1
            assert entries[0]["matcher"] == "Bash"
            assert _hal_commands(entries) == ["/usr/bin/hal"]

    def test_merges_with_existing(self):
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            settings_dir = Path(d) / ".claude"
            settings_dir.mkdir()
            existing = {"hooks": {"PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "other-tool"}]}
            ]}}
            (settings_dir / "settings.json").write_text(json.dumps(existing))

            _install_claude("/usr/bin/hal", project=True, no_configure=False)
            data = json.loads((settings_dir / "settings.json").read_text())
            assert sorted(_hal_commands(data["hooks"]["PreToolUse"])) == ["/usr/bin/hal", "other-tool"]

    def test_updates_existing_hal_hook(self):
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            settings_dir = Path(d) / ".claude"
            settings_dir.mkdir()
            existing = {"hooks": {"PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "/old/path/hal"}]}
            ]}}
            (settings_dir / "settings.json").write_text(json.dumps(existing))

            _install_claude("/new/path/hal", project=True, no_configure=False)
            data = json.loads((settings_dir / "settings.json").read_text())
            assert _hal_commands(data["hooks"]["PreToolUse"]) == ["/new/path/hal"]

    def test_no_configure_flag(self):
        """--no-configure should not add hooks, just write the file."""
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            _install_claude("/usr/bin/hal", project=True, no_configure=True)
            settings_path = Path(d) / ".claude" / "settings.json"
            assert settings_path.exists()
            data = json.loads(settings_path.read_text())
            assert "hooks" not in data or "PreToolUse" not in data.get("hooks", {})
