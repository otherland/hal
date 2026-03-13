"""YAML pack loading and rule compilation."""

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

try:
    import yaml
except ImportError:
    yaml = None  # fail-open: no packs if PyYAML missing


@dataclass
class Rule:
    """A single matching rule within a pack."""
    name: str = ""
    command: Optional[str] = None
    severity: str = "medium"
    reason: str = ""
    has_all: List[str] = field(default_factory=list)
    has_any: List[str] = field(default_factory=list)
    flags_contain: List[str] = field(default_factory=list)
    unless: List[str] = field(default_factory=list)
    unless_path: List[str] = field(default_factory=list)
    path_is: Optional[str] = None
    pattern: Optional[str] = None
    compiled: Optional[re.Pattern] = None
    rule_id: str = ""  # pack_id:rule_name, set during loading


@dataclass
class Pack:
    """A loaded rule pack."""
    id: str
    name: str
    keywords: List[str] = field(default_factory=list)
    rules: List[Rule] = field(default_factory=list)


def _compile_rule(pack_id: str, raw: dict) -> Rule:
    """Compile a raw YAML rule dict into a Rule, compiling regex if present."""
    rule = Rule(
        name=raw.get("name") or raw.get("id", "unnamed"),
        command=raw.get("command"),
        severity=raw.get("severity", "medium"),
        reason=raw.get("reason") or raw.get("description", ""),
        has_all=raw.get("has_all", []),
        has_any=raw.get("has_any", []),
        flags_contain=raw.get("flags_contain", []),
        unless=raw.get("unless", []),
        unless_path=raw.get("unless_path", []),
        path_is=raw.get("path_is"),
        pattern=raw.get("pattern"),
    )
    rule.rule_id = f"{pack_id}:{rule.name}"
    if rule.pattern:
        try:
            rule.compiled = re.compile(rule.pattern, re.ASCII)
        except re.error:
            print(f"hal: bad regex in {rule.rule_id}, skipping", file=sys.stderr)
            rule.compiled = None
    return rule


def load_packs(pack_dirs: Optional[List[str]] = None) -> List[Pack]:
    """Scan pack directories for *.yaml files and load them.

    Args:
        pack_dirs: List of directory paths to scan. Defaults to the
                   built-in packs/ directory next to the project root.
    """
    if yaml is None:
        print("hal: PyYAML not installed, no packs loaded", file=sys.stderr)
        return []

    if pack_dirs is None:
        default_dir = str(Path(__file__).resolve().parent.parent / "packs")
        pack_dirs = [default_dir]

    packs = []
    for dir_path in pack_dirs:
        dir_path = os.path.expanduser(dir_path)
        if not os.path.isdir(dir_path):
            continue
        for filename in sorted(os.listdir(dir_path)):
            if not filename.endswith((".yaml", ".yml")):
                continue
            filepath = os.path.join(dir_path, filename)
            try:
                with open(filepath) as f:
                    data = yaml.safe_load(f)
            except Exception:
                print(f"hal: failed to parse {filepath}, skipping", file=sys.stderr)
                continue

            if not isinstance(data, dict):
                continue

            pack_id = data.get("id", Path(filename).stem)
            rules = [_compile_rule(pack_id, r) for r in data.get("rules", [])
                     if isinstance(r, dict)]
            pack = Pack(
                id=pack_id,
                name=data.get("name", pack_id),
                keywords=data.get("keywords", []),
                rules=rules,
            )
            packs.append(pack)

    return packs
