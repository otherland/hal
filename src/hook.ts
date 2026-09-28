export const COPILOT = "copilot",
  CLAUDE = "claude";
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

export interface Decision {
  continue?: boolean;
  stopReason?: string;
  rule?: string;
  permissionDecision: "deny" | "ask";
  permissionDecisionReason: string;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

export function detectProtocol(d: HookPayload): string {
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
  protocol: string,
  action: "deny" | "ask",
  id: string,
  reason: string,
): string {
  const msg = `${action === "deny" ? "BLOCKED" : "WARNING"} [${id}]: ${reason}`;
  return JSON.stringify(
    protocol === COPILOT
      ? {
          continue: action === "ask",
          stopReason: msg,
          rule: id,
          permissionDecision: action,
          permissionDecisionReason: msg,
        }
      : {
          hookSpecificOutput: {
            hookEventName: "PreToolUse",
            rule: id,
            permissionDecision: action,
            permissionDecisionReason: msg,
          },
        },
  );
}
