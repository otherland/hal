import fs from "node:fs";
import path from "node:path";
import yaml from "js-yaml";

export type Rule = {
  name: string; command?: string; severity: string; reason: string;
  has_all: string[]; has_any: string[]; flags_contain: string[];
  unless: string[]; unless_path?: string[] | true; path_is?: string;
  pattern?: string; compiled?: RegExp; rule_id: string;
};
export type Pack = { id: string; name: string; keywords: string[]; rules: Rule[] };

export function loadPacks(dirs = [path.resolve(import.meta.dirname, "..", "packs")]): Pack[] {
  const result: Pack[] = [];
  for (const dir of dirs) {
    let files: string[];
    try { files = fs.readdirSync(dir).filter(f => /\.(yaml|yml)$/.test(f)).sort(); } catch { continue; }
    for (const file of files) {
      try {
        const raw = yaml.load(fs.readFileSync(path.join(dir, file), "utf8"));
        if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
        const data = raw as Record<string, unknown>;
        const id = String(data.id ?? path.basename(file, path.extname(file)));
        const rules = Array.isArray(data.rules) ? data.rules.filter(r => r && typeof r === "object").map(r => compileRule(id, r as Record<string, unknown>)) : [];
        result.push({ id, name: String(data.name ?? id), keywords: list(data.keywords), rules });
      } catch { /* fail open, like the Python loader */ }
    }
  }
  return result;
}
const list = (v: unknown): string[] => Array.isArray(v) ? v.map(String) : [];
function compileRule(pack: string, raw: Record<string, unknown>): Rule {
  const name = String(raw.name ?? raw.id ?? "unnamed");
  let compiled: RegExp | undefined;
  if (raw.regex || raw.pattern) { try { compiled = new RegExp(String(raw.regex ?? raw.pattern), "u"); } catch { /* skip bad regex */ } }
  return { name, command: raw.command == null ? undefined : String(raw.command), severity: String(raw.severity ?? "medium"),
    reason: String(raw.reason ?? raw.description ?? ""), has_all: list(raw.has_all), has_any: list(raw.has_any),
    flags_contain: list(raw.flags_contain), unless: list(raw.unless),
    unless_path: raw.unless_path === true ? true : list(raw.unless_path), path_is: raw.path_is == null ? undefined : String(raw.path_is),
    pattern: raw.pattern == null ? undefined : String(raw.pattern), compiled, rule_id: `${pack}:${name}` };
}
