"""Tests for hal.packs — YAML pack loading."""

import os
import tempfile

import yaml

from hal.packs import Pack, Rule, load_packs


class TestLoadPacks:
    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            packs = load_packs([d])
            assert packs == []

    def test_load_single_pack(self):
        with tempfile.TemporaryDirectory() as d:
            pack_data = {
                "name": "test-pack",
                "description": "A test pack",
                "keywords": ["rm"],
                "rules": [
                    {
                        "name": "no-rm-rf",
                        "reason": "Block rm -rf",
                        "has_all": ["rm"],
                        "flags_contain": ["-r", "-f"],
                        "severity": "block",
                    }
                ],
            }
            with open(os.path.join(d, "test.yaml"), "w") as f:
                yaml.dump(pack_data, f)

            packs = load_packs([d])
            assert len(packs) == 1
            assert packs[0].name == "test-pack"
            assert len(packs[0].rules) == 1
            assert packs[0].rules[0].name == "no-rm-rf"
            assert packs[0].rules[0].has_all == ["rm"]
            assert packs[0].rules[0].rule_id == "test:no-rm-rf"

    def test_regex_compiled(self):
        with tempfile.TemporaryDirectory() as d:
            pack_data = {
                "name": "regex-pack",
                "rules": [{"name": "r1", "pattern": r"rm\s+-rf"}],
            }
            with open(os.path.join(d, "regex.yaml"), "w") as f:
                yaml.dump(pack_data, f)

            packs = load_packs([d])
            assert packs[0].rules[0].compiled is not None
            assert packs[0].rules[0].compiled.search("rm -rf /")

    def test_bad_yaml_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "bad.yaml"), "w") as f:
                f.write(": : : invalid\n\t\tyaml: [")
            packs = load_packs([d])
            assert packs == []

    def test_nonexistent_dir(self):
        packs = load_packs(["/nonexistent/dir/that/should/not/exist"])
        assert packs == []

    def test_keywords_from_yaml(self):
        with tempfile.TemporaryDirectory() as d:
            pack_data = {
                "name": "kw-pack",
                "keywords": ["rm", "sudo"],
                "rules": [
                    {"name": "r1", "has_all": ["rm", "-rf"], "has_any": ["sudo"]},
                ],
            }
            with open(os.path.join(d, "kw.yaml"), "w") as f:
                yaml.dump(pack_data, f)

            packs = load_packs([d])
            assert "rm" in packs[0].keywords
            assert "sudo" in packs[0].keywords

    def test_default_pack_dir(self):
        """load_packs with no args should use built-in packs/ dir."""
        packs = load_packs()
        assert len(packs) >= 1
        names = [p.name for p in packs]
        assert "core.git" in names

    def test_regex_ascii_flag(self):
        """Compiled regex should use re.ASCII flag."""
        import re
        with tempfile.TemporaryDirectory() as d:
            pack_data = {
                "name": "ascii-test",
                "rules": [{"name": "r1", "pattern": r"\w+"}],
            }
            with open(os.path.join(d, "ascii.yaml"), "w") as f:
                yaml.dump(pack_data, f)
            packs = load_packs([d])
            assert packs[0].rules[0].compiled.flags & re.ASCII

    def test_missing_fields_defaults(self):
        """Rules with minimal fields should get sensible defaults."""
        with tempfile.TemporaryDirectory() as d:
            pack_data = {
                "name": "minimal",
                "rules": [{"name": "bare"}],
            }
            with open(os.path.join(d, "minimal.yaml"), "w") as f:
                yaml.dump(pack_data, f)
            packs = load_packs([d])
            rule = packs[0].rules[0]
            assert rule.name == "bare"
            assert rule.severity == "medium"
            assert rule.has_all == []
            assert rule.flags_contain == []
            assert rule.compiled is None

    def test_custom_pack_dirs(self):
        """Should load from custom directories."""
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            for i, d in enumerate([d1, d2]):
                pack_data = {"name": f"pack-{i}", "rules": [{"name": f"r{i}"}]}
                with open(os.path.join(d, f"p{i}.yaml"), "w") as f:
                    yaml.dump(pack_data, f)
            packs = load_packs([d1, d2])
            assert len(packs) == 2
            names = {p.name for p in packs}
            assert "pack-0" in names
            assert "pack-1" in names

    def test_non_dict_yaml_skipped(self):
        """YAML that parses to a list (not dict) should be skipped."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "list.yaml"), "w") as f:
                yaml.dump(["not", "a", "dict"], f)
            packs = load_packs([d])
            assert packs == []

    def test_id_fallback_from_filename(self):
        """Pack id should default to filename stem if not in YAML."""
        with tempfile.TemporaryDirectory() as d:
            pack_data = {"name": "test", "rules": []}
            with open(os.path.join(d, "my-rules.yaml"), "w") as f:
                yaml.dump(pack_data, f)
            packs = load_packs([d])
            assert packs[0].id == "my-rules"

    def test_rule_name_from_id_field(self):
        """_compile_rule should accept 'id' as fallback for 'name'."""
        with tempfile.TemporaryDirectory() as d:
            pack_data = {
                "name": "compat",
                "rules": [{"id": "old-style-id", "severity": "block"}],
            }
            with open(os.path.join(d, "compat.yaml"), "w") as f:
                yaml.dump(pack_data, f)
            packs = load_packs([d])
            assert packs[0].rules[0].name == "old-style-id"

    def test_all_builtin_packs_load(self):
        """All built-in YAML packs should load without errors."""
        packs = load_packs()
        assert len(packs) >= 5  # git, filesystem, docker, aws, azure
        for pack in packs:
            assert pack.name
            assert isinstance(pack.rules, list)
