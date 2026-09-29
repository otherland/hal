import fs from "node:fs";
import path from "node:path";
import { repoRoot } from "./install.js";
import type { PackDiagnostic } from "./packs.js";

interface CopilotConfig {
  trustedFolders?: unknown;
}
interface CopilotHookFile {
  version?: unknown;
  hooks?: { preToolUse?: unknown };
}

function isTrusted(root: string, configFile: string): string {
  try {
    const config = JSON.parse(
      fs.readFileSync(configFile, "utf8"),
    ) as CopilotConfig;
    const folders = Array.isArray(config.trustedFolders)
      ? config.trustedFolders.filter(
          (folder): folder is string => typeof folder === "string",
        )
      : [];
    const trusted = folders.some((folder) => {
      const resolved = path.resolve(folder);
      return root === resolved || root.startsWith(resolved + path.sep);
    });
    return trusted
      ? `trusted by ${configFile}`
      : `${root} is not in ${configFile}'s trustedFolders`;
  } catch {
    return `trustedFolders not found in ${configFile}`;
  }
}

export function doctor(diagnostics: readonly PackDiagnostic[] = []): number {
  const root = repoRoot();
  const file = path.join(root, ".github", "hooks", "hal.json");
  console.log("HAL doctor\n");
  console.log(`Repository: ${root}`);
  if (diagnostics.length) console.log(formatDiagnostics(diagnostics));
  if (!fs.existsSync(file)) {
    console.log(
      "✗ hook file: missing (.github/hooks/hal.json)\n\nStatus: not installed",
    );
    return 1;
  }
  try {
    const hook = JSON.parse(fs.readFileSync(file, "utf8")) as CopilotHookFile;
    if (
      hook.version !== 1 ||
      !Array.isArray(hook.hooks?.preToolUse) ||
      !hook.hooks.preToolUse.length
    )
      throw new Error("missing version 1 preToolUse hook");
  } catch (error) {
    console.log(`✗ hook file: invalid (${String(error)})\n\nStatus: invalid`);
    return 1;
  }
  console.log("✓ hook file: .github/hooks/hal.json\n✓ preToolUse configured");
  const home =
    process.env.COPILOT_HOME || path.join(process.env.HOME || "", ".copilot");
  const configFile = path.join(home, "config.json");
  const override =
    (process.env.GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS || "").toLowerCase() ===
    "true";
  const reason = override
    ? "GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS is enabled"
    : isTrusted(root, configFile);
  if (override || reason.startsWith("trusted by")) {
    if (diagnostics.length) {
      console.log("\nStatus: configured with invalid pack rules");
      return 1;
    }
    console.log(
      `✓ repository trust: ${reason}\n\nStatus: configured and trusted`,
    );
    return 0;
  }
  console.log(
    `! repository trust: ${reason}\n\nStatus: ${
      diagnostics.length
        ? "configured-but-untrusted with invalid pack rules"
        : "configured-but-untrusted"
    }\nAction: trust this repository before unattended Copilot use`,
  );
  return 1;
}

function formatDiagnostics(diagnostics: readonly PackDiagnostic[]): string {
  const messages = diagnostics
    .map((diagnostic) => `! pack: ${diagnostic.file}: ${diagnostic.message}`)
    .join("\n");
  return messages;
}
