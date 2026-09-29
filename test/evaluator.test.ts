import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
  evaluate,
  flags,
  match,
  normalize,
  shellSplit,
} from "../src/evaluate.js";
import { loadPacks, type Pack, type Rule } from "../src/packs.js";
import type { Config } from "../src/config.js";

const packs = loadPacks();
const config = (overrides: Partial<Config> = {}): Config => ({
  packs: [],
  packDirs: [],
  allow: [],
  allowRules: [],
  allowPrefixes: [],
  severityThreshold: "high",
  ...overrides,
});
const rule = (overrides: Partial<Rule> = {}): Rule => ({
  name: "test",
  command: "rm",
  severity: "block",
  reason: "",
  hasAll: [],
  hasAny: [],
  flagsContain: [],
  unless: [],
  ruleId: "test:r",
  ...overrides,
});
const custom = (): Pack[] => [
  {
    id: "test",
    name: "test",
    keywords: ["git"],
    rules: [
      rule({
        command: "git",
        hasAll: ["push"],
        flagsContain: ["f"],
        unless: ["--force-with-lease"],
        ruleId: "test:push",
      }),
    ],
  },
];

test("tokenization, normalization, and flags preserve shell edge cases", () => {
  assert.deepEqual(shellSplit(`echo "a b" 'c d' e\\ f`), [
    "echo",
    "a b",
    "c d",
    "e f",
  ]);
  assert.deepEqual(
    normalize(["sudo", "-u", "root", "env", "A=1", "\\git", "push"]),
    ["git", "push"],
  );
  assert.deepEqual(normalize(["env", "-i", "git", "push"]), ["git", "push"]);
  assert.deepEqual(normalize(["command", "-v", "git"]), [
    "command",
    "-v",
    "git",
  ]);
  assert.deepEqual(normalize(["/opt/custom/tool", "arg"]), [
    "/opt/custom/tool",
    "arg",
  ]);
  const f = flags(["rm", "-rf", "--recursive", "--format=oneline"]);
  assert.ok(
    f.has("-r") && f.has("-f") && f.has("--recursive") && f.has("--format"),
  );
});

test("rule matching handles all/any flags, exemptions, paths, and keywords", () => {
  assert.equal(
    match(
      ["rm", "-rf", "/"],
      flags(["rm", "-rf", "/"]),
      rule({ hasAll: ["-rf"], flagsContain: ["f"] }),
    ),
    true,
  );
  assert.equal(
    match(["rm", "/"], flags(["rm", "/"]), rule({ hasAll: ["-rf"] })),
    false,
  );
  assert.equal(
    match(
      ["git", "push", "--dry-run"],
      flags(["git", "push", "--dry-run"]),
      rule({ command: "git", has_all: ["push"], unless: ["--dry-run"] }),
    ),
    false,
  );
  assert.equal(
    match(
      ["rm", "node_modules"],
      flags(["rm", "node_modules"]),
      rule({ unlessPath: ["node_modules"] }),
    ),
    false,
  );
  assert.equal(
    match(["rm", "/"], flags(["rm", "/"]), rule({ pathIs: ["/"] })),
    true,
  );
});

test("segmentation, inline commands, heredocs, and sanitized data are evaluated", () => {
  assert.equal(
    evaluate("echo 'git push --force' && git status", packs).action,
    "allow",
  );
  assert.equal(evaluate("sudo env CI=1 git clean -f", packs).action, "block");
  assert.equal(evaluate("git commit -m 'rm -rf /'", packs).action, "allow");
  assert.equal(evaluate("bash -c 'rm -rf /'", packs).action, "block");
  assert.equal(evaluate("python -c 'echo hello'", packs).action, "allow");
  assert.equal(evaluate("bash <<'END'\nrm -rf /\nEND", packs).action, "block");
  assert.equal(
    evaluate("cat <<EOF | sh\ngit push --force\nEOF", packs).action,
    "block",
  );
});

test("evaluation honors allow lists and severity thresholds", () => {
  assert.equal(
    evaluate("git push --force", custom(), config()).action,
    "block",
  );
  assert.equal(
    evaluate("git push --force-with-lease", custom(), config()).action,
    "allow",
  );
  assert.equal(
    evaluate(
      "git push --force",
      custom(),
      config({ allow: ["git push --force"] }),
    ).action,
    "allow",
  );
  assert.equal(
    evaluate(
      "git push --force",
      custom(),
      config({ allowRules: ["test:push"] }),
    ).action,
    "allow",
  );
  assert.equal(
    evaluate(
      "git push --force",
      custom(),
      config({ allowPrefixes: ["git push"] }),
    ).action,
    "allow",
  );
  const warning = [
    {
      ...custom()[0],
      rules: [rule({ command: "git", hasAll: ["push"], severity: "warn" })],
    },
  ];
  assert.equal(
    evaluate("git push", warning, config({ severityThreshold: "block" }))
      .action,
    "allow",
  );
});

test("built-in packs cover destructive operations and safe exceptions", () => {
  const cases: [string, "block" | "allow"][] = [
    ["git reset --hard HEAD~1", "block"],
    ["git reset --soft HEAD~1", "allow"],
    ["git push --force origin main", "block"],
    ["git push --force-with-lease", "allow"],
    ["git clean -f", "block"],
    ["git clean -f -n", "allow"],
    ["git stash clear", "block"],
    ["git branch -D feature", "block"],
    ["git push -f origin main", "block"],
    ["rm -rf /var/data", "block"],
    ["rm -rf node_modules", "allow"],
    ["rm -rf ./node_modules", "allow"],
    ["rm -rf /tmp", "allow"],
    ["rm -rf /tmp/file", "allow"],
    ["rm -rf node_modules src", "block"],
    ["chmod 777 /etc/passwd", "block"],
    ["chmod 644 file.txt", "allow"],
    ["mkfs /dev/sda1", "block"],
    ["mkfs.ext4 /dev/sda1", "allow"],
    ["docker system prune -a", "block"],
    ["docker ps", "allow"],
    ["aws s3 rm s3://bucket --recursive", "block"],
    ["aws ec2 terminate-instances --instance-ids i-123", "block"],
    ["aws s3 ls", "allow"],
    ["az group delete --name mygroup", "block"],
    ["az vm list", "allow"],
    ["sudo git push --force", "block"],
    ["env VAR=1 rm -rf /", "block"],
    ["/usr/bin/rm -rf /", "block"],
    ["ls -la", "allow"],
    ["cat /etc/hosts", "allow"],
    ["echo hello world", "allow"],
    ["npm install express", "allow"],
    ["python3 script.py", "allow"],
  ];
  for (const [command, action] of cases)
    assert.equal(evaluate(command, packs).action, action, command);
});

test("allow commands are exact while custom packs retain built-ins", () => {
  assert.equal(
    evaluate(
      "git push --force",
      packs,
      config({ allow: ["git push"] }),
    ).action,
    "block",
  );
  assert.equal(
    evaluate("git push --force", packs, config({ packs: ["core.filesystem"] }))
      .action,
    "allow",
  );
});
