import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

interface ClaudeHook {
  type?: string;
  command?: string;
}
interface ClaudeEntry {
  matcher?: string;
  hooks?: ClaudeHook[];
}
interface ClaudeSettings {
  hooks?: { PreToolUse?: ClaudeEntry[] };
}

export function repoRoot(): string {
  try {
    return execFileSync("git", ["rev-parse", "--show-toplevel"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    }).trim();
  } catch {
    throw new Error("Copilot installation must be run inside a Git repository");
  }
}

function readSettings(file: string): ClaudeSettings {
  try {
    const value: unknown = JSON.parse(fs.readFileSync(file, "utf8"));
    return value && typeof value === "object" && !Array.isArray(value)
      ? (value as ClaudeSettings)
      : {};
  } catch {
    return {};
  }
}

export function install(
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
    const settings = readSettings(file);
    if (!noConfigure) {
      const hooks = (settings.hooks ??= {});
      const entries = (hooks.PreToolUse ??= []);
      const newHooks: ClaudeHook[] = [{ type: "command", command }];
      const entry: ClaudeEntry = {
        matcher: "Bash",
        hooks: newHooks,
      };
      const existing = entries.filter((item) =>
        item.hooks?.some((hook) => String(hook.command || "").includes("hal")),
      );
      if (existing.length) existing.forEach((item) => (item.hooks = newHooks));
      else entries.push(entry);
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
