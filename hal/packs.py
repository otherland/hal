"""YAML pack loading and rule compilation."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Rule:
    """A single matching rule within a pack."""
    id: str = ""
    description: str = ""
    severity: str = "block"
    has_all: list[str] = field(default_factory=list)
    has_any: list[str] = field(default_factory=list)
    flags_contain: list[str] = field(default_factory=list)
    unless: list[str] = field(default_factory=list)
    unless_path: bool = False
    path_is: list[str] = field(default_factory=list)
    regex: re.Pattern | None = None


@dataclass
class Pack:
    """A loaded rule pack."""
    name: str
    description: str = ""
    source: str = ""  # file path it was loaded from
    rules: list[Rule] = field(default_factory=list)
    keywords: set[str] = field(default_factory=set)


def _compile_rule(raw: dict) -> Rule:
    """Compile a raw YAML rule dict into a Rule, compiling regex if present."""
    rule = Rule(
        id=raw.get("id", ""),
        description=raw.get("description", ""),
        severity=raw.get("severity", "block"),
        has_all=raw.get("has_all", []),
        has_any=raw.get("has_any", []),
        flags_contain=raw.get("flags_contain", []),
        unless=raw.get("unless", []),
        unless_path=raw.get("unless_path", False),
        path_is=raw.get("path_is", []),
    )
    if "regex" in raw:
        rule.regex = re.compile(raw["regex"], re.ASCII)
    return rule


def _build_keywords(rules: list[Rule]) -> set[str]:
    """Build a keyword index from rules for fast pre-filtering."""
    keywords = set()
    for rule in rules:
        keywords.update(rule.has_all)
        keywords.update(rule.has_any)
    return keywords


def load_packs(pack_dirs: list[str] | None = None) -> list[Pack]:
    """Scan pack directories for *.yaml files and load them.

    Args:
        pack_dirs: List of directory paths to scan. Defaults to the
                   built-in packs/ directory next to the project root.
    """
    if pack_dirs is None:
        # Default: packs/ directory at project root (sibling of hal/)
        default_dir = str(Path(__file__).resolve().parent.parent / "packs")
        pack_dirs = [default_dir]

    packs = []
    for dir_path in pack_dirs:
        if not os.path.isdir(dir_path):
            continue
        for filename in sorted(os.listdir(dir_path)):
            if not filename.endswith((".yaml", ".yml")):
                continue
            filepath = os.path.join(dir_path, filename)
            try:
                with open(filepath) as f:
                    data = yaml.safe_load(f)
            except (yaml.YAMLError, OSError):
                continue  # fail-open: skip bad files

            if not isinstance(data, dict):
                continue

            rules = [_compile_rule(r) for r in data.get("rules", []) if isinstance(r, dict)]
            pack = Pack(
                name=data.get("name", Path(filename).stem),
                description=data.get("description", ""),
                source=filepath,
                rules=rules,
                keywords=_build_keywords(rules),
            )
            packs.append(pack)

    return packs
