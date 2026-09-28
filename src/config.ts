import fs from "node:fs";
import path from "node:path";
import yaml from "js-yaml";
import type { Config } from "./evaluate.js";

export function loadConfig(cwd = process.cwd()): Config {
  const values: Record<string, unknown> = {};
  for (const file of [path.join(process.env.HOME ?? "", ".config/hal/config.yaml"), path.join(cwd, ".hal.yaml")]) {
    try {
      const data = yaml.load(fs.readFileSync(file, "utf8"));
      if (data && typeof data === "object" && !Array.isArray(data)) {
        for (const [key, value] of Object.entries(data as Record<string, unknown>)) {
          if (Array.isArray(values[key]) && Array.isArray(value)) values[key] = [...values[key] as unknown[], ...value];
          else values[key] = value;
        }
      }
    } catch { /* optional configuration is fail-open */ }
  }
  const list = (v: unknown): string[] => Array.isArray(v) ? v.map(String) : [];
  return { packs:list(values.packs), pack_dirs:list(values.pack_dirs), allow:list(values.allow), allow_rules:list(values.allow_rules), allow_prefixes:list(values.allow_prefixes), severity_threshold:String(values.severity_threshold ?? "high") };
}
