import fs from "node:fs";
import path from "node:path";
import yaml from "js-yaml";
import { isSeverity, type Severity } from "./types.js";

export type Rule = {
  name: string;
  command?: string;
  severity: Severity;
  reason: string;
  hasAll?: string[];
  hasAny?: string[];
  flagsContain?: string[];
  unless?: string[];
  unlessPath?: string[] | true;
  pathIs?: string | string[];
  pattern?: string;
  compiled?: RegExp;
  ruleId: string;
};
export type Pack = {
  id: string;
  name: string;
  keywords: string[];
  rules: Rule[];
};

export function loadPacks(
  dirs = [path.resolve(import.meta.dirname, "..", "packs")],
  selectedIds: string[] = [],
): Pack[] {
  const result: Pack[] = [];
  for (const dir of dirs) {
    let files: string[];
    try {
      files = fs
        .readdirSync(dir)
        .filter((f) => /\.(yaml|yml)$/.test(f))
        .sort();
    } catch {
      continue;
    }
    for (const file of files) {
      try {
        const raw = yaml.load(fs.readFileSync(path.join(dir, file), "utf8"));
        if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
        const data = raw as Record<string, unknown>;
        const id = String(data.id ?? path.basename(file, path.extname(file)));
        if (selectedIds.length > 0 && !selectedIds.includes(id)) continue;
        const rules = Array.isArray(data.rules)
          ? data.rules
              .filter((r) => r && typeof r === "object")
              .map((r) => compileRule(id, r as Record<string, unknown>))
          : [];
        result.push({
          id,
          name: String(data.name ?? id),
          keywords: list(data.keywords),
          rules,
        });
      } catch {
        /* malformed packs are ignored so evaluation fails open */
      }
    }
  }
  return result;
}
const list = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : []);
const severity = (value: unknown): Severity | undefined =>
  value === undefined ? "medium" : isSeverity(value) ? value : undefined;
function compileRule(pack: string, raw: Record<string, unknown>): Rule {
  const name = String(raw.name ?? raw.id ?? "unnamed");
  let compiled: RegExp | undefined;
  if (raw.regex || raw.pattern) {
    try {
      compiled = new RegExp(String(raw.regex ?? raw.pattern), "u");
    } catch {
      /* skip bad regex */
    }
  }
  const ruleSeverity = severity(raw.severity);
  if (!ruleSeverity) throw new Error(`invalid severity for ${name}`);
  return {
    name,
    command: raw.command == null ? undefined : String(raw.command),
    severity: ruleSeverity,
    reason: String(raw.reason ?? raw.description ?? ""),
    hasAll: list(raw.has_all),
    hasAny: list(raw.has_any),
    flagsContain: list(raw.flags_contain),
    unless: list(raw.unless),
    unlessPath: raw.unless_path === true ? true : list(raw.unless_path),
    pathIs:
      raw.path_is == null
        ? undefined
        : Array.isArray(raw.path_is)
          ? raw.path_is.map(String)
          : String(raw.path_is),
    pattern: raw.pattern == null ? undefined : String(raw.pattern),
    compiled,
    ruleId: `${pack}:${name}`,
  };
}
