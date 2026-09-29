export const SEVERITIES = [
  "info",
  "low",
  "medium",
  "warn",
  "high",
  "block",
] as const;

export type Severity = (typeof SEVERITIES)[number];

export type Protocol = "copilot" | "claude";

export type PermissionDecision = "deny" | "ask";

export const isSeverity = (value: unknown): value is Severity =>
  typeof value === "string" &&
  SEVERITIES.includes(value as Severity);
