#!/usr/bin/env node
import fs from "node:fs";
import { loadConfig } from "./config.js";
import { evaluate } from "./evaluate.js";
import { detectProtocol, extractCommand, decisionOutput } from "./hook.js";
import { loadPacks } from "./packs.js";
import path from "node:path";
import { execFileSync } from "node:child_process";

function main(): void {
  try {
    const args = process.argv.slice(2);
    const config = loadConfig(),
      packs = loadPacks(config.pack_dirs.length ? config.pack_dirs : undefined);
    if (args[0] === "install") {
      install(
        args.includes("--claude"),
        args.includes("--project"),
        args.includes("--no-configure"),
      );
      return;
    }
    if (args[0] === "doctor") {
      process.exitCode = doctor();
      return;
    }
    if (args[0] === "test") {
      const d = evaluate(args.slice(1).join(" "), packs, config);
      console.log(
        d.action === "block"
          ? `✗ BLOCKED  ${d.command}\n  rule: ${d.rule_id}\n  reason: ${d.reason}\n  severity: ${d.severity}`
          : `✓ ALLOWED  ${args.slice(1).join(" ")}`,
      );
      process.exitCode = d.action === "block" ? 1 : 0;
      return;
    }
    const raw = fs.readFileSync(0, "utf8");
    if (!raw.trim()) return;
    const data = JSON.parse(raw) as Record<string, unknown>,
      command = extractCommand(data);
    if (!command) return;
    const d = evaluate(command, packs, config);
    if (d.action === "block")
      console.log(
        decisionOutput(
          detectProtocol(data),
          ["warn", "medium", "low", "info"].includes(d.severity)
            ? "ask"
            : "deny",
          d.rule_id,
          d.reason,
        ),
      );
  } catch {
    /* hooks must fail open */
  }
}
function repoRoot(): string {
  try {
    return execFileSync("git", ["rev-parse", "--show-toplevel"], {
      encoding: "utf8",
    }).trim();
  } catch {
    return process.cwd();
  }
}
function install(
  claude: boolean,
  project: boolean,
  noConfigure: boolean,
): void {
  const command = process.env.HAL_PATH || "hal";
  if (claude) {
    const file = project
      ? path.join(".claude", "settings.json")
      : path.join(process.env.HOME || "", ".claude", "settings.json");
    fs.mkdirSync(path.dirname(file), { recursive: true });
    let settings: any = {};
    try {
      settings = JSON.parse(fs.readFileSync(file, "utf8"));
    } catch {}
    if (!noConfigure) {
      settings.hooks ??= {};
      settings.hooks.PreToolUse ??= [];
      const entry = { matcher: "Bash", hooks: [{ type: "command", command }] };
      const existing = settings.hooks.PreToolUse.filter((x: any) =>
        x?.hooks?.some((h: any) => String(h.command || "").includes("hal")),
      );
      if (existing.length)
        existing.forEach((x: any) => (x.hooks = entry.hooks));
      else settings.hooks.PreToolUse.push(entry);
    }
    fs.writeFileSync(file, JSON.stringify(settings, null, 2) + "\n");
    console.log(`hal: installed Claude Code hook at ${file}`);
    return;
  }
  const file = path.join(repoRoot(), ".github", "hooks", "hal.json");
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(
    file,
    JSON.stringify(
      {
        version: 1,
        hooks: {
          preToolUse: [
            {
              type: "command",
              bash: command,
              powershell: command,
              cwd: ".",
              timeoutSec: 30,
            },
          ],
        },
      },
      null,
      2,
    ) + "\n",
  );
  console.log(`hal: installed Copilot hook at ${file}`);
}
function doctor(): number {
  const root = repoRoot(),
    file = path.join(root, ".github", "hooks", "hal.json");
  console.log("HAL doctor\n");
  console.log(`Repository: ${root}`);
  if (!fs.existsSync(file)) {
    console.log(
      "✗ hook file: missing (.github/hooks/hal.json)\n\nStatus: not installed",
    );
    return 1;
  }
  let data: any;
  try {
    data = JSON.parse(fs.readFileSync(file, "utf8"));
    if (
      data.version !== 1 ||
      !Array.isArray(data.hooks?.preToolUse) ||
      !data.hooks.preToolUse.length
    )
      throw new Error("missing version 1 preToolUse hook");
  } catch (e) {
    console.log(`✗ hook file: invalid (${e})\n\nStatus: invalid`);
    return 1;
  }
  console.log("✓ hook file: .github/hooks/hal.json\n✓ preToolUse configured");
  const home =
      process.env.COPILOT_HOME || path.join(process.env.HOME || "", ".copilot"),
    config = path.join(home, "config.json");
  let trusted = false,
    reason = "";
  if (
    (process.env.GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS || "").toLowerCase() ===
    "true"
  ) {
    trusted = true;
    reason = "GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS is enabled";
  } else {
    try {
      const values =
        JSON.parse(fs.readFileSync(config, "utf8")).trustedFolders || [];
      trusted = values.some((v: string) => {
        try {
          return (
            root === path.resolve(v) ||
            root.startsWith(path.resolve(v) + path.sep)
          );
        } catch {
          return false;
        }
      });
      reason = trusted
        ? "trusted by " + config
        : `${root} is not in ${config}'s trustedFolders`;
    } catch {
      reason = `trustedFolders not found in ${config}`;
    }
  }
  if (trusted) {
    console.log(
      `✓ repository trust: ${reason}\n\nStatus: configured and trusted`,
    );
    return 0;
  }
  console.log(
    `! repository trust: ${reason}\n\nStatus: configured-but-untrusted\nAction: trust this repository before unattended Copilot use`,
  );
  return 1;
}
main();
