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
        # We have YAML packs in packs/ — should load them
        assert len(packs) >= 1
        names = [p.name for p in packs]
        assert "core.git" in names
