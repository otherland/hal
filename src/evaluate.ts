import path from "node:path";
import type { Pack, Rule } from "./packs.js";

const LONG: Record<string, string[]> = {
  "--recursive": ["-r", "-R"],
  "--force": ["-f"],
  "--verbose": ["-v"],
  "--quiet": ["-q"],
  "--all": ["-a"],
  "--interactive": ["-i"],
  "--no-preserve-root": ["--no-preserve-root"],
};
const BINARIES = new Set(
  "git rm mv cp chmod chown chgrp ln sudo env command bash sh zsh fish python python3 node ruby perl docker kubectl aws gcloud az curl wget ssh scp rsync kill killall pkill dd mkfs fdisk iptables systemctl journalctl".split(
    " ",
  ),
);
const ORDER: Record<string, number> = {
  info: 0,
  low: 1,
  medium: 2,
  warn: 3,
  high: 4,
  block: 5,
};
export type Config = {
  packs: string[];
  packDirs?: string[];
  allow: string[];
  allowRules?: string[];
  allowPrefixes?: string[];
  severityThreshold?: string;
  /** @deprecated YAML field compatibility. */
  pack_dirs?: string[];
  /** @deprecated YAML field compatibility. */
  allow_rules?: string[];
  /** @deprecated YAML field compatibility. */
  allow_prefixes?: string[];
  /** @deprecated YAML field compatibility. */
  severity_threshold?: string;
};
export type Decision = {
  action: "allow" | "block";
  rule_id: string;
  reason: string;
  severity: string;
  command: string;
};

const configValue = (config: Config) => ({
  allow: config.allow,
  allowRules: config.allowRules ?? config.allow_rules ?? [],
  allowPrefixes: config.allowPrefixes ?? config.allow_prefixes ?? [],
  severityThreshold:
    config.severityThreshold ?? config.severity_threshold ?? "high",
});

export function shellSplit(s: string): string[] {
  const out: string[] = [];
  let cur = "",
    quote = "",
    esc = false;
  for (const c of s) {
    if (esc) {
      cur += c;
      esc = false;
    } else if (c === "\\" && quote !== "'") esc = true;
    else if (quote) {
      if (c === quote) quote = "";
      else cur += c;
    } else if (c === "'" || c === '"') quote = c;
    else if (/\s/.test(c)) {
      if (cur) {
        out.push(cur);
        cur = "";
      }
    } else cur += c;
  }
  if (esc) cur += "\\";
  if (cur) out.push(cur);
  return out;
}
export function normalize(input: string[]): string[] {
  let t = [...input],
    changed = true;
  while (changed && t.length) {
    changed = false;
    if (t[0].startsWith("\\") && t[0].length > 1) {
      t[0] = t[0].slice(1);
      changed = true;
      continue;
    }
    if (t[0] === "sudo" || t[0] === "env" || t[0] === "command") {
      if (t[0] === "command" && ["-v", "-V"].includes(t[1])) break;
      const kind = String(t.shift());
      changed = true;
      while (t.length) {
        const next = String(t[0]);
        if (
          (kind === "sudo" && ["-u", "-g"].includes(next)) ||
          (kind === "env" && next === "-u")
        )
          t.splice(0, 2);
        else if (
          (kind === "env" && !next.startsWith("-") && next.includes("=")) ||
          (next.startsWith("-") && next !== "--")
        )
          t.shift();
        else if (next === "--") {
          t.shift();
          break;
        } else break;
      }
      continue;
    }
    if (t[0].includes("/")) {
      const b = path.basename(t[0]);
      if (BINARIES.has(b)) {
        t[0] = b;
        changed = true;
      }
    }
  }
  return t;
}
export function flags(tokens: string[]): Set<string> {
  const out = new Set<string>();
  for (const t of tokens)
    if (t.startsWith("-") && t !== "-" && t !== "--") {
      out.add(t);
      const base = t.split("=")[0];
      if (base !== t) out.add(base);
      if (LONG[base]) LONG[base].forEach((x) => out.add(x));
      else if (!t.startsWith("--") && t.length > 2)
        [...t.slice(1)].forEach((x) => out.add(`-${x}`));
    }
  return out;
}
const paths = (t: string[]) =>
  t.slice(1).filter((x) => x !== "--" && !x.startsWith("-"));
function glob(s: string, p: string): boolean {
  const re =
    "^" +
    p
      .replace(/[.+^${}()|[\]\\]/g, "\\$&")
      .replace(/\*/g, ".*")
      .replace(/\?/g, ".") +
    "$";
  return new RegExp(re).test(s);
}
const hasMissingTokens = (required: string[], tokens: Set<string>): boolean =>
  required.some((token) => !tokens.has(token));
const hasNoMatchingToken = (required: string[], tokens: Set<string>): boolean =>
  required.length > 0 && !required.some((token) => tokens.has(token));
const hasMissingFlags = (required: string[], flags: Set<string>): boolean =>
  required.some((flag) => !flags.has(flag.length === 1 ? `-${flag}` : flag));
const hasExemption = (
  exemptions: string[] | undefined,
  tokens: Set<string>,
): boolean => (exemptions ?? []).some((token) => tokens.has(token));
export function match(tokens: string[], fs: Set<string>, r: Rule): boolean {
  if (!tokens.length || (r.command && tokens[0] !== r.command)) return false;
  const hasAll = r.hasAll ?? r.has_all ?? [];
  const hasAny = r.hasAny ?? r.has_any ?? [];
  const flagsContain = r.flagsContain ?? r.flags_contain ?? [];
  const unlessPath = r.unlessPath ?? r.unless_path;
  const pathIs = r.pathIs ?? r.path_is;
  const all = new Set(tokens),
    combined = new Set([...all, ...fs]);
  if (hasMissingTokens(hasAll, all) || hasNoMatchingToken(hasAny, combined))
    return false;
  if (hasMissingFlags(flagsContain, fs) || hasExemption(r.unless, combined))
    return false;
  if (unlessPath) {
    for (const p of paths(tokens)) {
      if (p.includes("..")) {
        if (unlessPath === true) return true;
        continue;
      }
      if (Array.isArray(unlessPath) && unlessPath.some((x) => glob(p, x)))
        return false;
    }
  }
  return (
    !pathIs ||
    paths(tokens).some((p) =>
      Array.isArray(pathIs) ? pathIs.includes(p) : p === pathIs,
    )
  );
}
function sanitize(t: string[]): string {
  if (!t.length) return "";
  const cmd = t[0],
    data = new Set(["echo", "printf"]),
    flagsData: Record<string, Set<string>> = {
      git: new Set(["-m", "--message", "--grep"]),
      grep: new Set(["-e", "--regexp"]),
      rg: new Set(["-e", "--regexp"]),
      curl: new Set(["-d", "--data", "-H", "--header"]),
      gh: new Set(["-t", "--title", "-b", "--body"]),
    };
  let skip = false;
  return t
    .map((x, i) => {
      if (skip) {
        skip = false;
        return "_".repeat(x.length);
      }
      if (i > 0 && data.has(cmd) && !x.includes("$(") && !x.includes("`"))
        return "_".repeat(x.length);
      if (flagsData[cmd]?.has(x)) {
        skip = true;
        return x;
      }
      return x;
    })
    .join(" ");
}
function segments(s: string): string[] {
  const out: string[] = [];
  let cur = "",
    q = "";
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c === "'" || c === '"') {
      if (!q) q = c;
      else if (q === c) q = "";
      cur += c;
      continue;
    }
    if (!q && (c === ";" || c === "|" || c === "&")) {
      if (s[i + 1] === c) i++;
      if (cur.trim()) out.push(cur.trim());
      cur = "";
    } else cur += c;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}
const inline = (t: string[]) => {
  const map: Record<string, string> = {
      bash: "-c",
      sh: "-c",
      zsh: "-c",
      fish: "-c",
      python: "-c",
      python3: "-c",
      ruby: "-e",
      perl: "-e",
      node: "-e",
    },
    f = map[t[0]];
  const i = f ? t.indexOf(f) : -1;
  return i >= 0 ? t[i + 1] : undefined;
};
const interpreters = new Set([
  "bash",
  "sh",
  "zsh",
  "fish",
  "python",
  "python3",
  "ruby",
  "perl",
  "node",
]);
function heredoc(command: string): string | undefined {
  const marker = command.match(/<<-?\s*['"]?(\w+)['"]?/);
  if (!marker) return undefined;
  const body: string[] = [];
  let capturing = false;
  for (const line of command.split("\n")) {
    if (capturing) {
      if (line.trim() === marker[1]) break;
      body.push(line);
    } else if (line.includes("<<") && line.includes(marker[1]))
      capturing = true;
  }
  if (!body.length) return undefined;
  const before = command
    .slice(0, marker.index ?? 0)
    .trim()
    .split(/\s+/);
  if (before.length && interpreters.has(before[0])) return body.join("\n");
  const targets = command
    .split("|")
    .slice(1)
    .map((s) => s.trim().split(/\s+/)[0]);
  return targets.some((t) => interpreters.has(t)) ? body.join("\n") : undefined;
}
export function evaluate(
  command: string,
  packs: Pack[],
  config: Config = {
    packs: [],
    packDirs: [],
    allow: [],
    allowRules: [],
    allowPrefixes: [],
    severityThreshold: "high",
  },
  depth = 0,
): Decision {
  const allow = {
    action: "allow" as const,
    rule_id: "",
    reason: "",
    severity: "",
    command,
  };
  const settings = configValue(config);
  if (isAllowed(command, settings)) return allow;
  if (depth < 1) {
    const body = heredoc(command);
    if (body)
      for (const line of body.split("\n")) {
        const d = evaluate(line.trim(), packs, config, depth + 1);
        if (d.action === "block") return d;
      }
  }
  for (const seg of segments(command)) {
    const t = normalize(shellSplit(seg));
    if (!t.length) continue;
    const f = flags(t);
    for (const p of packs) {
      if (p.keywords.length && !p.keywords.includes(t[0])) continue;
      for (const r of p.rules) {
        if (isBelowThreshold(r, settings.severityThreshold)) continue;
        let hit = match(t, f, r);
        if (!hit && r.compiled)
          hit = r.compiled.test(sanitize(t)) || r.compiled.test(seg);
        if (hit && !settings.allowRules.includes(r.rule_id))
          return {
            action: "block",
            rule_id: r.rule_id,
            reason: r.reason,
            severity: r.severity,
            command: seg,
          };
      }
    }
    if (depth < 1) {
      const sub = inline(t);
      if (sub) {
        const d = evaluate(sub, packs, config, depth + 1);
        if (d.action === "block") return d;
      }
      const body = heredoc(seg);
      if (body) {
        for (const line of body.split("\n")) {
          const d = evaluate(line.trim(), packs, config, depth + 1);
          if (d.action === "block") return d;
        }
      }
    }
  }
  return allow;
}
const isAllowed = (
  command: string,
  settings: ReturnType<typeof configValue>,
): boolean =>
  !command.trim() ||
  settings.allow.some(
    (value) =>
      command.trim() === value || command.trim().startsWith(value + " "),
  ) ||
  settings.allowPrefixes.some((value) => command.trim().startsWith(value));
const isBelowThreshold = (rule: Rule, threshold: string): boolean =>
  (ORDER[rule.severity] ?? 2) < (ORDER[threshold] ?? 4);
