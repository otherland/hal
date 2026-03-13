"""Configuration loading for HAL."""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Config:
    """HAL configuration — merged from global + project-level files."""
    packs: list[str] = field(default_factory=list)
    allow: list[str] = field(default_factory=list)
    allow_rules: list[str] = field(default_factory=list)
    allow_prefixes: list[str] = field(default_factory=list)
    severity_threshold: str = "high"
    pack_dirs: list[str] = field(default_factory=list)


_GLOBAL_CONFIG = Path.home() / ".config" / "hal" / "config.yaml"
_PROJECT_CONFIG = ".hal.yaml"


def _load_yaml(path: str | Path) -> dict:
    """Load a YAML file, returning {} on any error (fail-open)."""
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def _merge(base: dict, override: dict) -> dict:
    """Merge override into base. Lists are concatenated, scalars replaced."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], list) and isinstance(val, list):
            result[key] = result[key] + val
        else:
            result[key] = val
    return result


def load_config(project_dir: str | None = None) -> Config:
    """Load config from global (~/.config/hal/config.yaml) and project (.hal.yaml).

    Project-level config wins on merge. All fields optional — zero-config works.
    """
    global_data = _load_yaml(_GLOBAL_CONFIG)

    project_data = {}
    if project_dir:
        project_path = Path(project_dir) / _PROJECT_CONFIG
        project_data = _load_yaml(project_path)
    else:
        # Try CWD
        project_data = _load_yaml(_PROJECT_CONFIG)

    merged = _merge(global_data, project_data)

    return Config(
        packs=merged.get("packs", []),
        allow=merged.get("allow", []),
        allow_rules=merged.get("allow_rules", []),
        allow_prefixes=merged.get("allow_prefixes", []),
        severity_threshold=merged.get("severity_threshold", "high"),
        pack_dirs=merged.get("pack_dirs", []),
    )
