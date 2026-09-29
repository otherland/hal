#!/usr/bin/env node
import fs from "node:fs";
import { parseArgs } from "node:util";
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

const VERSION = "0.1.1";

function usage(): void {
  console.log(`Usage: hal <command>

Commands:
  hal install [--claude] [--project] [--no-configure]
  hal doctor
  hal test <command>
  hal --help
  hal --version`);
}

function evaluateCommand(command: string): void {
  const config = loadConfig();
  const packs = [
    ...loadPacks(undefined, config.packs),
    ...loadPacks(config.packDirs, config.packs),
  ];
  const verdict = evaluate(command, packs, config);
  console.log(
    verdict.action === "block"
      ? `✗ BLOCKED  ${verdict.command}\n  rule: ${verdict.ruleId}\n  reason: ${verdict.reason}\n  severity: ${verdict.severity}`
      : `✓ ALLOWED  ${command}`,
  );
  process.exitCode = verdict.action === "block" ? 1 : 0;
}

function runHook(): void {
  try {
    const raw = fs.readFileSync(0, "utf8");
    if (!raw.trim()) return;
    const parsed: unknown = JSON.parse(raw);
    if (!isHookPayload(parsed)) return;
    const command = extractCommand(parsed);
    if (!command) return;
    const config = loadConfig();
    const packs = [
      ...loadPacks(undefined, config.packs),
      ...loadPacks(config.packDirs, config.packs),
    ];
    const verdict = evaluate(command, packs, config);
    if (verdict.action === "block")
      console.log(
        decisionOutput(
          detectProtocol(parsed),
          verdict.severity === "block" || verdict.severity === "high"
            ? "deny"
            : "ask",
          verdict.ruleId ?? "unknown",
          verdict.reason,
        ),
      );
  } catch {
    /* hooks must fail open */
  }
}

function main(): void {
  const [command, ...arguments_] = process.argv.slice(2);
  if (!command) {
    if (!process.stdin.isTTY) return runHook();
    usage();
    return;
  }
  if (command === "--help" || command === "-h") return usage();
  if (command === "--version" || command === "-v") {
    console.log(VERSION);
    return;
  }
  if (command === "install") {
    const { values, positionals } = parseArgs({
      args: arguments_,
      options: {
        claude: { type: "boolean" },
        project: { type: "boolean" },
        "no-configure": { type: "boolean" },
      },
      allowPositionals: true,
      strict: true,
    });
    if (positionals.length) throw new Error("install does not accept arguments");
    install(!!values.claude, !!values.project, !!values["no-configure"]);
    return;
  }
  if (command === "doctor") {
    if (arguments_.length) throw new Error("doctor does not accept arguments");
    process.exitCode = doctor();
    return;
  }
  if (command === "test") {
    if (!arguments_.length) throw new Error("test requires a command");
    evaluateCommand(arguments_.join(" "));
    return;
  }
  throw new Error(`unknown command: ${command}\nRun "hal --help" for usage.`);
}

try {
  main();
} catch (error) {
  console.error(`hal: ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
}
