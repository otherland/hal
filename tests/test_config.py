"""Tests for hal.config — configuration loading."""

import os
import tempfile

import yaml

from hal.config import Config, load_config


class TestLoadConfig:
    def test_default_config(self):
        """Zero-config should return sensible defaults."""
        config = load_config(project_dir="/nonexistent")
        assert isinstance(config, Config)
        assert config.severity_threshold == "high"
        assert config.packs == []
        assert config.allow == []

    def test_project_config(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = {
                "packs": ["core.git", "core.filesystem"],
                "allow": ["echo *"],
                "severity_threshold": "medium",
            }
            with open(os.path.join(d, ".hal.yaml"), "w") as f:
                yaml.dump(cfg, f)

            config = load_config(project_dir=d)
            assert config.packs == ["core.git", "core.filesystem"]
            assert config.allow == ["echo *"]
            assert config.severity_threshold == "medium"

    def test_merge_lists(self):
        """Project config lists should concatenate with global."""
        with tempfile.TemporaryDirectory() as d:
            cfg = {
                "allow": ["ls"],
                "pack_dirs": ["/custom/packs"],
            }
            with open(os.path.join(d, ".hal.yaml"), "w") as f:
                yaml.dump(cfg, f)

            config = load_config(project_dir=d)
            assert "ls" in config.allow
            assert "/custom/packs" in config.pack_dirs

    def test_missing_config_file(self):
        """Missing config files should not error (fail-open)."""
        config = load_config(project_dir="/tmp/definitely_not_a_project")
        assert isinstance(config, Config)
