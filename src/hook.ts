import type { PermissionDecision, Protocol } from "./types.js";

export const COPILOT: Protocol = "copilot";
export const CLAUDE: Protocol = "claude";
export interface HookPayload {
  event?: unknown;
  toolName?: unknown;
  toolInput?: unknown;
  toolArgs?: unknown;
  hookSpecificInput?: unknown;
  tool_input?: unknown;
}

export function isHookPayload(value: unknown): value is HookPayload {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

interface CopilotHookResponse {
  continue: boolean;
  stopReason: string;
  permissionDecision: PermissionDecision;
  permissionDecisionReason: string;
}
interface ClaudeHookResponse {
  hookSpecificOutput: {
    hookEventName: "PreToolUse";
    permissionDecision: PermissionDecision;
    permissionDecisionReason: string;
  };
}
export type HookResponse = CopilotHookResponse | ClaudeHookResponse;

function isObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

export function detectProtocol(d: HookPayload): Protocol {
  if (
    d.event === "pre-tool-use" ||
    ["run_shell_command", "run-shell-command"].includes(String(d.toolName)) ||
    "toolInput" in d ||
    "toolArgs" in d
  )
    return COPILOT;
  if ("hookSpecificInput" in d || "tool_input" in d) return CLAUDE;
  return COPILOT;
}
export function extractCommand(d: HookPayload): string | undefined {
  const get = (v: unknown): string | undefined =>
    typeof v === "string"
      ? v
      : v && typeof v === "object"
        ? String(
            (v as Record<string, unknown>).command ??
              (v as Record<string, unknown>).input ??
              "",
          ) || undefined
        : undefined;
  const h = d.hookSpecificInput;
  if (isObject(h) && typeof h.command === "string") return h.command;
  for (const k of ["tool_input", "toolInput"]) {
    const v = get((d as Record<string, unknown>)[k]);
    if (v) return v;
  }
  const raw = d.toolArgs;
  if (typeof raw === "string") {
    try {
      return get(JSON.parse(raw));
    } catch {
      return raw;
    }
  }
  return get(raw);
}
export function decisionOutput(
  protocol: Protocol,
  action: PermissionDecision,
  id: string,
  reason: string,
): string {
  const msg = `${action === "deny" ? "BLOCKED" : "WARNING"} [${id}]: ${reason}`;
  const response: HookResponse =
    protocol === COPILOT
      ? {
          continue: action === "ask",
          stopReason: msg,
          permissionDecision: action,
          permissionDecisionReason: msg,
        }
      : {
          hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: action,
            permissionDecisionReason: msg,
          },
        };
  return JSON.stringify(response);
}
