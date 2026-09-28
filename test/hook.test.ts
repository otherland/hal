import { strict as assert } from "node:assert";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { test } from "node:test";
import {
  CLAUDE,
  COPILOT,
  decisionOutput,
  detectProtocol,
  extractCommand,
} from "../src/hook.js";

test("detects protocols and extracts all supported command envelopes", () => {
  assert.equal(detectProtocol({}), COPILOT);
  assert.equal(
    detectProtocol({ hookSpecificInput: { command: "rm -rf /" } }),
    CLAUDE,
  );
  assert.equal(detectProtocol({ tool_input: "git push --force" }), CLAUDE);
  assert.equal(detectProtocol({ toolInput: { command: "rm -rf /" } }), COPILOT);
  assert.equal(detectProtocol({ toolArgs: { command: "rm -rf /" } }), COPILOT);
  const cases: [Record<string, unknown>, string][] = [
    [
      { hookSpecificInput: { command: "git push --force" } },
      "git push --force",
    ],
    [{ tool_input: "rm -rf /" }, "rm -rf /"],
    [{ tool_input: { command: "git push" } }, "git push"],
    [{ toolInput: "rm -rf /" }, "rm -rf /"],
    [
      { toolInput: { command: "docker system prune -a" } },
      "docker system prune -a",
    ],
    [
      { toolArgs: { command: "aws s3 rm --recursive" } },
      "aws s3 rm --recursive",
    ],
    [{ toolArgs: "git reset --hard" }, "git reset --hard"],
    [{ tool_input: { input: "echo hello" } }, "echo hello"],
  ];
  for (const [data, expected] of cases)
    assert.equal(extractCommand(data), expected);
  assert.equal(extractCommand({}), undefined);
});

test("formats deny and ask decisions for both protocols", () => {
  const copilot = JSON.parse(
    decisionOutput(COPILOT, "deny", "core.git:push-force", "bad push"),
  );
  assert.equal(copilot.continue, false);
  assert.equal(copilot.permissionDecision, "deny");
  assert.equal(copilot.rule, "core.git:push-force");
  const claude = JSON.parse(
    decisionOutput(CLAUDE, "ask", "test:warn", "careful"),
  );
  assert.equal(claude.hookSpecificOutput.permissionDecision, "ask");
  assert.equal(claude.hookSpecificOutput.rule, "test:warn");
});

test("CLI hook protocol fails open and emits decisions", () => {
  const root = path.resolve(import.meta.dirname, "..");
  const run = (input: string) =>
    execFileSync(
      process.execPath,
      [
        "--import",
        path.join(root, "node_modules/tsx/dist/loader.mjs"),
        path.join(root, "src/cli.ts"),
      ],
      { cwd: root, input, encoding: "utf8" },
    );
  const claude = JSON.parse(
    run(JSON.stringify({ hookSpecificInput: { command: "git push --force" } })),
  );
  assert.equal(claude.hookSpecificOutput.permissionDecision, "deny");
  assert.equal(
    run(JSON.stringify({ hookSpecificInput: { command: "git status" } })),
    "",
  );
  const copilot = JSON.parse(
    run(JSON.stringify({ toolInput: { command: "rm -rf /" } })),
  );
  assert.equal(copilot.continue, false);
  assert.equal(
    JSON.parse(run(JSON.stringify({ toolArgs: "git reset --hard HEAD" })))
      .continue,
    false,
  );
  assert.equal(
    run(JSON.stringify({ tool_input: { code: "console.log('hello')" } })),
    "",
  );
  assert.equal(run("not valid json {{{"), "");
  assert.equal(run(""), "");
});
