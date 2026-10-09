"""YAML pack loading and rule compilation."""

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

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
    unless_path: Union[List[str], bool] = field(default_factory=list)
    path_is: Union[str, List[str], None] = None
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


@dataclass
class PackDiagnostic:
    """A problem found while loading a pack file."""
    file: str
    message: str


BUILTIN_PACK_DIR = str(Path(__file__).resolve().parent.parent / "packs")
SEVERITIES = ("info", "low", "medium", "warn", "high", "block")


def _str_list(value) -> List[str]:
    return [str(v) for v in value] if isinstance(value, list) else []


def _compile_rule(pack_id: str, raw: dict) -> Rule:
    """Compile a raw YAML rule dict into a Rule, compiling regex if present.

    Raises ValueError for an invalid severity or regex, so the caller can
    skip just this rule.
    """
    name = str(raw.get("name") or raw.get("id") or "unnamed")
    severity = raw.get("severity", "medium")
    if severity not in SEVERITIES:
        raise ValueError(f"invalid severity for {name}")
    path_is = raw.get("path_is")
    pattern = raw.get("regex") or raw.get("pattern")
    rule = Rule(
        name=name,
        command=None if raw.get("command") is None else str(raw["command"]),
        severity=severity,
        reason=str(raw.get("reason") or raw.get("description") or ""),
        has_all=_str_list(raw.get("has_all")),
        has_any=_str_list(raw.get("has_any")),
        flags_contain=_str_list(raw.get("flags_contain")),
        unless=_str_list(raw.get("unless")),
        unless_path=True if raw.get("unless_path") is True else _str_list(raw.get("unless_path")),
        path_is=_str_list(path_is) if isinstance(path_is, list) else (None if path_is is None else str(path_is)),
        pattern=None if pattern is None else str(pattern),
        rule_id=f"{pack_id}:{name}",
    )
    if rule.pattern:
        try:
            rule.compiled = re.compile(rule.pattern, re.ASCII)
        except re.error as e:
            raise ValueError(f"invalid regex for {name}: {e}") from e
    return rule


def _compile_rules(pack_id: str, raw_rules, filepath: str, diagnostics: list) -> List[Rule]:
    """Compile each rule, recording and skipping only the malformed ones."""
    if not isinstance(raw_rules, list):
        return []
    rules = []
    for raw in raw_rules:
        if not isinstance(raw, dict):
            diagnostics.append(PackDiagnostic(filepath, "rule must be an object"))
            continue
        try:
            rules.append(_compile_rule(pack_id, raw))
        except ValueError as e:
            diagnostics.append(PackDiagnostic(filepath, str(e)))
    return rules


def load_packs(
    pack_dirs: Optional[List[str]] = None,
    selected_ids: Optional[List[str]] = None,
    diagnostics: Optional[List[PackDiagnostic]] = None,
) -> List[Pack]:
    """Scan pack directories for *.yaml files and load them.

    Args:
        pack_dirs: List of directory paths to scan. Defaults to the
                   built-in packs/ directory next to the project root.
        selected_ids: Only load packs with these ids; empty loads all.
        diagnostics: Collects problems with pack files and rules.
    """
    if diagnostics is None:
        diagnostics = []
    if yaml is None:
        print("hal: PyYAML not installed, no packs loaded", file=sys.stderr)
        return []

    if pack_dirs is None:
        pack_dirs = [BUILTIN_PACK_DIR]

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
            except Exception as e:
                diagnostics.append(PackDiagnostic(filepath, str(e)))
                continue

            if not isinstance(data, dict):
                continue

            pack_id = str(data.get("id", Path(filename).stem))
            if selected_ids and pack_id not in selected_ids:
                continue
            pack = Pack(
                id=pack_id,
                name=str(data.get("name", pack_id)),
                keywords=_str_list(data.get("keywords")),
                rules=_compile_rules(pack_id, data.get("rules"), filepath, diagnostics),
            )
            packs.append(pack)

    return packs


def load_configured_packs(config, diagnostics: Optional[List[PackDiagnostic]] = None) -> List[Pack]:
    """Load built-in packs plus the config's pack_dirs, filtered by its packs list."""
    custom_dirs = list(dict.fromkeys(
        os.path.abspath(os.path.expanduser(d)) for d in config.pack_dirs
    ))
    return (load_packs(None, config.packs, diagnostics)
            + load_packs(custom_dirs, config.packs, diagnostics))
