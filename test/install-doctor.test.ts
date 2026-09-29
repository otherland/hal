import { strict as assert } from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { execFileSync, spawnSync } from "node:child_process";
import { test } from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const temp = () =>
  fs.mkdtempSync(path.join(path.dirname(process.cwd()), ".hal-test-"));
const run = (cwd: string, args: string[], env: Record<string, string> = {}) =>
  execFileSync(
    process.execPath,
    [
      "--import",
      path.join(root, "node_modules/tsx/dist/loader.mjs"),
      path.join(root, "src/cli.ts"),
      ...args,
    ],
    {
      cwd,
      env: { ...process.env, HAL_PATH: "/usr/bin/hal", ...env },
      encoding: "utf8",
    },
  );
const runWithOutput = (
  cwd: string,
  args: string[],
  env: Record<string, string> = {},
) =>
  spawnSync(
    process.execPath,
    [
      "--import",
      path.join(root, "node_modules/tsx/dist/loader.mjs"),
      path.join(root, "src/cli.ts"),
      ...args,
    ],
    {
      cwd,
      env: { ...process.env, HAL_PATH: "/usr/bin/hal", ...env },
      encoding: "utf8",
    },
  );

const initializeRepo = (directory: string): void => {
  execFileSync("git", ["init", "--quiet"], { cwd: directory });
};

test("install creates Copilot hook and Claude project settings", () => {
  const d = temp();
  try {
    initializeRepo(d);
    run(d, ["install"]);
    const copilot = JSON.parse(
      fs.readFileSync(path.join(d, ".github/hooks/hal.json"), "utf8"),
    );
    assert.equal(copilot.version, 1);
    assert.equal(copilot.hooks.preToolUse[0].bash, "/usr/bin/hal");
    run(d, ["install", "--claude", "--project"]);
    const settings = JSON.parse(
      fs.readFileSync(path.join(d, ".claude/settings.json"), "utf8"),
    );
    assert.equal(settings.hooks.PreToolUse.length, 1);
    assert.equal(settings.hooks.PreToolUse[0].hooks[0].command, "/usr/bin/hal");
  } finally {
    fs.rmSync(d, { recursive: true, force: true });
  }
});

test("Claude install merges unrelated hooks, updates HAL, and supports no-configure", () => {
  const d = temp();
  try {
    initializeRepo(d);
    fs.mkdirSync(path.join(d, ".claude"), { recursive: true });
    fs.writeFileSync(
      path.join(d, ".claude/settings.json"),
      JSON.stringify({
        hooks: {
          PreToolUse: [
            {
              matcher: "Bash",
              hooks: [{ type: "command", command: "other-tool" }],
            },
            {
              matcher: "Bash",
              hooks: [{ type: "command", command: "/old/path/hal" }],
            },
          ],
        },
      }),
    );
    run(d, ["install", "--claude", "--project"]);
    const p = path.join(d, ".claude/settings.json");
    let settings = JSON.parse(fs.readFileSync(p, "utf8"));
    assert.equal(settings.hooks.PreToolUse.length, 2);
    assert.ok(
      settings.hooks.PreToolUse.some(
        (x: any) => x.hooks[0].command === "other-tool",
      ),
    );
    assert.equal(
      settings.hooks.PreToolUse.find((x: any) =>
        x.hooks[0].command.includes("hal"),
      ).hooks[0].command,
      "/usr/bin/hal",
    );
    fs.rmSync(p);
    run(d, ["install", "--claude", "--project", "--no-configure"]);
    settings = JSON.parse(fs.readFileSync(p, "utf8"));
    assert.equal(settings.hooks, undefined);
  } finally {
    fs.rmSync(d, { recursive: true, force: true });
  }
});

test("doctor reports missing, invalid, untrusted, and trusted repositories", () => {
  const d = temp();
  try {
    initializeRepo(d);
    assert.throws(() => run(d, ["doctor"]));
    run(d, ["install"]);
    assert.throws(() => run(d, ["doctor"]));
    fs.writeFileSync(path.join(d, ".github/hooks/hal.json"), "{bad json");
    assert.throws(() => run(d, ["doctor"]));
    run(d, ["install"]);
    fs.writeFileSync(path.join(d, ".copilot.json"), "{}");
    const home = path.join(d, "home");
    fs.mkdirSync(path.join(home, ".copilot"), { recursive: true });
    fs.writeFileSync(
      path.join(home, ".copilot/config.json"),
      JSON.stringify({ trustedFolders: [d] }),
    );
    const output = run(d, ["doctor"], { HOME: home });
    assert.match(output, /configured and trusted/);
  } finally {
    fs.rmSync(d, { recursive: true, force: true });
  }
});

test("CLI shows help and reports installation failures", () => {
  const d = temp();
  try {
    assert.match(run(d, ["--help"]), /Usage: hal/);
    assert.match(run(d, ["--version"]), /^0\.1\.3\n$/);
    assert.throws(
      () => run(d, ["unknown-command"]),
      /unknown command: unknown-command/,
    );
    assert.throws(
      () => run(d, ["install"]),
      /must be run inside a Git repository/,
    );
  } finally {
    fs.rmSync(d, { recursive: true, force: true });
  }
});

test("CLI distinguishes confirmation from a denied command", () => {
  const d = temp();
  try {
    assert.match(run(d, ["test", "git branch -D feature"]), /CONFIRM/);
    const denied = runWithOutput(d, ["test", "git push --force"]);
    assert.equal(denied.status, 1);
    assert.match(denied.stdout, /BLOCKED/);
  } finally {
    fs.rmSync(d, { recursive: true, force: true });
  }
});

test("doctor reports invalid configured pack rules without disabling valid rules", () => {
  const d = temp();
  try {
    initializeRepo(d);
    run(d, ["install"]);
    const home = path.join(d, "home");
    fs.mkdirSync(path.join(home, ".copilot"), { recursive: true });
    fs.writeFileSync(
      path.join(home, ".copilot/config.json"),
      JSON.stringify({ trustedFolders: [d] }),
    );
    fs.mkdirSync(path.join(d, "packs"));
    fs.writeFileSync(
      path.join(d, "packs", "custom.yaml"),
      "id: custom\nkeywords: [erase]\nrules: [{id: invalid, severity: critical}, {id: valid, command: erase, severity: block}]\n",
    );
    fs.writeFileSync(path.join(d, ".hal.yaml"), "pack_dirs: [packs]\n");
    const doctor = runWithOutput(d, ["doctor"], { HOME: home });
    assert.equal(doctor.status, 1);
    assert.match(doctor.stdout, /invalid severity/);
    const testCommand = runWithOutput(d, ["test", "erase"], { HOME: home });
    assert.equal(testCommand.status, 1);
    assert.match(testCommand.stdout, /BLOCKED/);
    assert.match(testCommand.stderr, /invalid severity/);
  } finally {
    fs.rmSync(d, { recursive: true, force: true });
  }
});

test("doctor reports invalid pack rules before hook installation", () => {
  const d = temp();
  try {
    initializeRepo(d);
    fs.mkdirSync(path.join(d, "packs"));
    fs.writeFileSync(
      path.join(d, "packs", "custom.yaml"),
      "id: custom\nrules: [{id: invalid, severity: critical}]\n",
    );
    fs.writeFileSync(path.join(d, ".hal.yaml"), "pack_dirs: [packs]\n");
    const doctor = runWithOutput(d, ["doctor"]);
    assert.equal(doctor.status, 1);
    assert.match(doctor.stdout, /invalid severity/);
    assert.match(doctor.stdout, /hook file: missing/);
  } finally {
    fs.rmSync(d, { recursive: true, force: true });
  }
});
