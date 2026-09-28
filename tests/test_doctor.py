"""Tests for HAL's read-only Copilot doctor."""

import json
import os
from pathlib import Path
from unittest import mock

from hal.doctor import run


def _write_hook(root: Path) -> None:
    hook = root / ".github" / "hooks" / "hal.json"
    hook.parent.mkdir(parents=True)
    hook.write_text(json.dumps({
        "version": 1,
        "hooks": {
            "preToolUse": [{"type": "command", "bash": "/usr/local/bin/hal"}],
        },
    }))


class TestDoctor:
    def test_missing_hook(self, tmp_path, capsys):
        with mock.patch("hal.doctor.repo_root", return_value=tmp_path):
            assert run() == 1
        assert "Status: not installed" in capsys.readouterr().out

    def test_untrusted_hook(self, tmp_path, capsys):
        _write_hook(tmp_path)
        home = tmp_path / "copilot"
        home.mkdir()
        (home / "config.json").write_text(json.dumps({"trustedFolders": []}))
        with (
            mock.patch("hal.doctor.repo_root", return_value=tmp_path),
            mock.patch.dict(os.environ, {"COPILOT_HOME": str(home)}, clear=False),
            mock.patch("shutil.which", return_value="/usr/local/bin/hal"),
        ):
            assert run() == 1
        assert "configured-but-untrusted" in capsys.readouterr().out

    def test_trusted_hook(self, tmp_path, capsys):
        _write_hook(tmp_path)
        home = tmp_path / "copilot"
        home.mkdir()
        (home / "config.json").write_text(
            json.dumps({"trustedFolders": [str(tmp_path)]})
        )
        with (
            mock.patch("hal.doctor.repo_root", return_value=tmp_path),
            mock.patch.dict(os.environ, {"COPILOT_HOME": str(home)}, clear=False),
            mock.patch("shutil.which", return_value="/usr/local/bin/hal"),
        ):
            assert run() == 0
        assert "configured and trusted" in capsys.readouterr().out

    def test_prompt_mode_override(self, tmp_path, capsys):
        _write_hook(tmp_path)
        with (
            mock.patch("hal.doctor.repo_root", return_value=tmp_path),
            mock.patch.dict(
                os.environ,
                {"GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS": "true"},
                clear=False,
            ),
        ):
            assert run() == 0
        assert "PROMPT_MODE_REPO_HOOKS" in capsys.readouterr().out
