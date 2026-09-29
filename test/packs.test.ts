import { strict as assert } from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { loadPacks } from "../src/packs.js";

const temp = () =>
  fs.mkdtempSync(path.join(path.dirname(process.cwd()), ".hal-test-"));
test("pack loading handles defaults, custom directories, malformed YAML, and regexes", () => {
  const d = temp();
  try {
    fs.writeFileSync(
      path.join(d, "test.yaml"),
      "name: test-pack\nkeywords: [rm]\nrules:\n  - name: no-rm-rf\n    reason: Block rm -rf\n    has_all: [rm]\n    flags_contain: [-r, -f]\n    severity: block\n",
    );
    fs.writeFileSync(
      path.join(d, "regex.yaml"),
      "name: regex-pack\nrules:\n  - name: r1\n    pattern: 'rm\\s+-rf'\n",
    );
    fs.writeFileSync(path.join(d, "list.yaml"), "- not\n- a dict\n");
    fs.writeFileSync(path.join(d, "bad.yaml"), ": : : invalid\n\t\tyaml: [");
    const loaded = loadPacks([d]);
    assert.equal(loaded.length, 2);
    assert.equal(
      loaded.find((p) => p.name === "test-pack")?.rules[0].ruleId,
      "test:no-rm-rf",
    );
    const regex = loaded.find((p) => p.name === "regex-pack")?.rules[0];
    assert.ok(regex?.compiled?.test("rm -rf /"));
    assert.equal(regex?.severity, "medium");
  } finally {
    fs.rmSync(d, { recursive: true, force: true });
  }
});
test("built-in and multiple custom pack directories load", () => {
  const d1 = temp(),
    d2 = temp();
  try {
    fs.writeFileSync(
      path.join(d1, "one.yaml"),
      "name: one\nrules: [{id: r1}]\n",
    );
    fs.writeFileSync(path.join(d2, "two.yaml"), "name: two\nrules: []\n");
    const custom = loadPacks([d1, d2]);
    assert.deepEqual(
      custom.map((p) => p.name),
      ["one", "two"],
    );
    const built = loadPacks();
    assert.ok(built.length >= 5 && built.some((p) => p.name === "core.git"));
  } finally {
    fs.rmSync(d1, { recursive: true, force: true });
    fs.rmSync(d2, { recursive: true, force: true });
  }
});

test("invalid rule severity skips only the malformed rule", () => {
  const d = temp();
  try {
    fs.writeFileSync(
      path.join(d, "invalid.yaml"),
      "id: invalid\nrules: [{id: unsafe, severity: critical}, {id: safe, severity: block}]\n",
    );
    const diagnostics = [];
    const packs = loadPacks([d], [], diagnostics);
    assert.deepEqual(
      packs[0]?.rules.map((rule) => rule.name),
      ["safe"],
    );
    assert.match(diagnostics[0]?.message ?? "", /invalid severity/);
  } finally {
    fs.rmSync(d, { recursive: true, force: true });
  }
});

test("invalid regular expressions skip only the malformed rule", () => {
  const d = temp();
  try {
    fs.writeFileSync(
      path.join(d, "invalid-regex.yaml"),
      "id: invalid-regex\nrules: [{id: invalid, pattern: '['}, {id: safe, severity: block}]\n",
    );
    const diagnostics = [];
    const packs = loadPacks([d], [], diagnostics);
    assert.deepEqual(
      packs[0]?.rules.map((rule) => rule.name),
      ["safe"],
    );
    assert.match(diagnostics[0]?.message ?? "", /Invalid regular expression/);
  } finally {
    fs.rmSync(d, { recursive: true, force: true });
  }
});

test("pack ids, rule id fallbacks, keywords, and nonexistent dirs are stable", () => {
  const d = temp();
  try {
    fs.writeFileSync(
      path.join(d, "my-rules.yaml"),
      "name: named\nkeywords: [rm, sudo]\nrules: [{id: old-style-id}]\n",
    );
    const loaded = loadPacks([d]);
    assert.equal(loaded[0].id, "my-rules");
    assert.deepEqual(loaded[0].keywords, ["rm", "sudo"]);
    assert.equal(loaded[0].rules[0].name, "old-style-id");
    assert.deepEqual(loadPacks(["/nonexistent/dir/that/should/not/exist"]), []);
  } finally {
    fs.rmSync(d, { recursive: true, force: true });
  }
});

test("selected pack ids filter built-ins and custom packs", () => {
  const d = temp();
  try {
    fs.writeFileSync(path.join(d, "custom.yaml"), "id: custom\nrules: []\n");
    assert.deepEqual(
      loadPacks(undefined, ["core.git"]).map((p) => p.id),
      ["core.git"],
    );
    assert.deepEqual(
      loadPacks([d], ["custom"]).map((p) => p.id),
      ["custom"],
    );
  } finally {
    fs.rmSync(d, { recursive: true, force: true });
  }
});

test("custom pack directories are additive to built-ins", () => {
  const d = temp();
  try {
    fs.writeFileSync(path.join(d, "custom.yaml"), "id: custom\nrules: []\n");
    const loaded = [...loadPacks(), ...loadPacks([d])];
    assert.ok(loaded.some((p) => p.id === "core.git"));
    assert.ok(loaded.some((p) => p.id === "custom"));
  } finally {
    fs.rmSync(d, { recursive: true, force: true });
  }
});
