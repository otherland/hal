import { strict as assert } from "node:assert";
import fs from "node:fs";
import { it } from "node:test";
import os from "node:os";
import path from "node:path";
import { evaluate } from "../src/evaluate.js";
import { loadPacks } from "../src/packs.js";
import { loadConfig } from "../src/config.js";
import {
  COPILOT,
  CLAUDE,
  decisionOutput,
  detectProtocol,
  extractCommand,
} from "../src/hook.js";

const packs = loadPacks();
it("blocks destructive commands and allows safe exceptions", () => {
  assert.equal(evaluate("git push --force", packs).action, "block");
  assert.equal(evaluate("git push --force-with-lease", packs).action, "allow");
  assert.equal(evaluate("rm -rf node_modules", packs).action, "allow");
});
it("evaluates heredocs and preserves hook protocol extraction", () => {
  assert.equal(evaluate("bash <<EOF\nrm -rf /\nEOF", packs).action, "block");
  assert.equal(
    evaluate("cat <<'END' | sh\ngit push --force\nEND", packs).action,
    "block",
  );
  assert.equal(
    extractCommand({ toolInput: { command: "git push --force" } }),
    "git push --force",
  );
  assert.equal(
    extractCommand({ toolArgs: '{"command":"rm -rf /"}' }),
    "rm -rf /",
  );
  assert.equal(detectProtocol({ toolInput: { command: "x" } }), "copilot");
  assert.equal(detectProtocol({ tool_input: { command: "x" } }), "claude");
});
it("handles command segmentation, wrappers, and regex-safe data", () => {
  assert.equal(
    evaluate("echo 'git push --force' && git status", packs).action,
    "allow",
  );
  assert.equal(evaluate("sudo env CI=1 git clean -f", packs).action, "block");
  assert.equal(evaluate("git commit -m 'rm -rf /'", packs).action, "allow");
});
it("formats Copilot and Claude decisions", () => {
  const copilot = JSON.parse(
    decisionOutput(COPILOT, "deny", "core.git:git-push-force", "unsafe"),
  );
  assert.deepEqual(copilot, {
    continue: false,
    stopReason: "BLOCKED [core.git:git-push-force]: unsafe",
    rule: "core.git:git-push-force",
    permissionDecision: "deny",
    permissionDecisionReason: "BLOCKED [core.git:git-push-force]: unsafe",
  });
  const claude = JSON.parse(
    decisionOutput(CLAUDE, "ask", "core.git:git-stash-drop", "review"),
  );
  assert.equal(claude.hookSpecificOutput.permissionDecision, "ask");
});
it("merges project configuration and supports allow lists", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "hal-test-"));
  try {
    fs.writeFileSync(
      path.join(dir, ".hal.yaml"),
      "allow: [git status]\nseverity_threshold: block\n",
    );
    const config = loadConfig(dir);
    assert.deepEqual(config.allow, ["git status"]);
    assert.equal(config.severity_threshold, "block");
    assert.equal(evaluate("git status", packs, config).action, "allow");
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
