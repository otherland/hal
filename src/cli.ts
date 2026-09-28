#!/usr/bin/env node
import fs from "node:fs";
import { loadConfig } from "./config.js";
import { evaluate } from "./evaluate.js";
import {
  detectProtocol,
  extractCommand,
  decisionOutput,
  isHookPayload,
} from "./hook.js";
import { loadPacks } from "./packs.js";
import { doctor } from "./doctor.js";
import { install } from "./install.js";

function main(): void {
  try {
    const args = process.argv.slice(2);
    const config = loadConfig();
    const packs = [
      ...loadPacks(undefined, config.packs),
      ...loadPacks(config.packDirs?.length ? config.packDirs : [], config.packs),
    ];
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
    const parsed: unknown = JSON.parse(raw);
    if (!isHookPayload(parsed)) return;
    const command = extractCommand(parsed);
    if (!command) return;
    const d = evaluate(command, packs, config);
    if (d.action === "block")
      console.log(
        decisionOutput(
          detectProtocol(parsed),
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
main();
