import { strict as assert } from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { loadConfig } from "../src/config.js";

const temp = () =>
  fs.mkdtempSync(path.join(path.dirname(process.cwd()), ".hal-test-"));
test("configuration defaults and missing files fail open", () => {
  const c = loadConfig(path.join(process.cwd(), ".does-not-exist"));
  assert.equal(c.severityThreshold, "warn");
  assert.deepEqual(c.packs, []);
  assert.deepEqual(c.allow, []);
});
test("project configuration loads and preserves list values", () => {
  const d = temp();
  try {
    fs.writeFileSync(
      path.join(d, ".hal.yaml"),
      'packs: [core.git, core.filesystem]\nallow: ["echo *"]\npack_dirs: [/custom/packs]\nseverity_threshold: medium\n',
    );
    const c = loadConfig(d);
    assert.deepEqual(c.packs, ["core.git", "core.filesystem"]);
    assert.deepEqual(c.allow, ["echo *"]);
    assert.deepEqual(c.packDirs, ["/custom/packs"]);
    assert.equal(c.severityThreshold, "medium");
  } finally {
    fs.rmSync(d, { recursive: true, force: true });
  }
});

test("invalid severity values fall back to the safe default", () => {
  const d = temp();
  try {
    fs.writeFileSync(
      path.join(d, ".hal.yaml"),
      "severity_threshold: critical\n",
    );
    assert.equal(loadConfig(d).severityThreshold, "warn");
  } finally {
    fs.rmSync(d, { recursive: true, force: true });
  }
});

test("project lists merge with global lists", () => {
  const home = temp(),
    project = temp();
  try {
    fs.mkdirSync(path.join(home, ".config/hal"), { recursive: true });
    fs.writeFileSync(
      path.join(home, ".config/hal/config.yaml"),
      "allow: [global]\npack_dirs: [/global]\n",
    );
    fs.writeFileSync(
      path.join(project, ".hal.yaml"),
      "allow: [project]\npack_dirs: [/project]\n",
    );
    const old = process.env.HOME;
    process.env.HOME = home;
    try {
      const c = loadConfig(project);
      assert.deepEqual(c.allow, ["global", "project"]);
      assert.deepEqual(c.packDirs, ["/global", "/project"]);
    } finally {
      if (old === undefined) delete process.env.HOME;
      else process.env.HOME = old;
    }
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
    fs.rmSync(project, { recursive: true, force: true });
  }
});
