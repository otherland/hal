import fs from "node:fs";
import path from "node:path";
import yaml from "js-yaml";
import type { Config } from "./evaluate.js";

interface RawConfig {
  packs?: unknown;
  pack_dirs?: unknown;
  allow?: unknown;
  allow_rules?: unknown;
  allow_prefixes?: unknown;
  severity_threshold?: unknown;
}

const stringList = (value: unknown): string[] =>
  Array.isArray(value) ? value.map(String) : [];

export function loadConfig(cwd = process.cwd()): Config {
  const values: RawConfig = {};
  for (const file of [
    path.join(process.env.HOME ?? "", ".config/hal/config.yaml"),
    path.join(cwd, ".hal.yaml"),
  ]) {
    try {
      const data = yaml.load(fs.readFileSync(file, "utf8"));
      if (data && typeof data === "object" && !Array.isArray(data)) {
        for (const [key, value] of Object.entries(data as RawConfig)) {
          const field = key as keyof RawConfig;
          const current = values[field];
          values[field] =
            Array.isArray(current) && Array.isArray(value)
              ? [...current, ...value]
              : value;
        }
      }
    } catch {
      /* optional configuration is fail-open */
    }
  }
  return {
    packs: stringList(values.packs),
    packDirs: stringList(values.pack_dirs),
    allow: stringList(values.allow),
    allowRules: stringList(values.allow_rules),
    allowPrefixes: stringList(values.allow_prefixes),
    severityThreshold: String(values.severity_threshold ?? "high"),
    // Keep the public object compatible with existing YAML-era callers.
    pack_dirs: stringList(values.pack_dirs),
    allow_rules: stringList(values.allow_rules),
    allow_prefixes: stringList(values.allow_prefixes),
    severity_threshold: String(values.severity_threshold ?? "high"),
  };
}
