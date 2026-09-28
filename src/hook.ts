export const COPILOT = "copilot", CLAUDE = "claude";
export function detectProtocol(d: Record<string, unknown>): string {
  if (d.event === "pre-tool-use" || ["run_shell_command","run-shell-command"].includes(String(d.toolName)) || "toolInput" in d || "toolArgs" in d) return COPILOT;
  return CLAUDE;
}
export function extractCommand(d: Record<string, unknown>): string | undefined {
  const get = (v: unknown): string | undefined => typeof v === "string" ? v : v && typeof v === "object" ? String((v as Record<string,unknown>).command ?? (v as Record<string,unknown>).input ?? "") || undefined : undefined;
  const h=d.hookSpecificInput; if(h && typeof h==="object" && "command" in h) return String((h as Record<string,unknown>).command);
  for(const k of ["tool_input","toolInput"]) { const v=get(d[k]); if(v)return v; }
  const raw=d.toolArgs; if(typeof raw==="string"){try{return get(JSON.parse(raw))}catch{return raw}} return get(raw);
}
export function decisionOutput(protocol:string, action:"deny"|"ask", id:string, reason:string): string {
  const msg=`${action==="deny"?"BLOCKED":"WARNING"} [${id}]: ${reason}`;
  return JSON.stringify(protocol===COPILOT ? {continue:action==="ask",stopReason:msg,permissionDecision:action,permissionDecisionReason:msg} : {hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:action,permissionDecisionReason:msg}});
}
