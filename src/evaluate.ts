import path from "node:path";
import type { Pack, Rule } from "./packs.js";
import { DEFAULT_CONFIG, type Config } from "./config.js";
import type { Severity } from "./types.js";

const LONG_FLAGS: Record<string, string[]> = {
  "--recursive": ["-r", "-R"],
  "--force": ["-f"],
  "--verbose": ["-v"],
  "--quiet": ["-q"],
  "--all": ["-a"],
  "--interactive": ["-i"],
  "--no-preserve-root": ["--no-preserve-root"],
};
const SHORT_TO_LONG: Record<string, string> = Object.fromEntries(
  Object.entries(LONG_FLAGS).flatMap(([long, shorts]) =>
    shorts.filter((short) => short !== long).map((short) => [short, long]),
  ),
);
const BINARIES = new Set(
  "git rm mv cp chmod chown chgrp ln sudo env command bash sh zsh fish python python3 node ruby perl docker kubectl aws gcloud az curl wget ssh scp rsync kill killall pkill dd mkfs fdisk iptables systemctl journalctl".split(
    " ",
  ),
);
const SEVERITY_ORDER: Record<Severity, number> = {
  info: 0,
  low: 1,
  medium: 2,
  warn: 3,
  high: 4,
  block: 5,
};
export type Verdict = {
  action: "allow" | "block";
  ruleId?: string;
  reason: string;
  severity?: Severity;
  command: string;
};

export function shellSplit(s: string): string[] {
  const tokens: string[] = [];
  let token = "";
  let quote = "";
  let escaping = false;

  for (const character of s) {
    if (escaping) {
      token += character;
      escaping = false;
    } else if (character === "\\" && quote !== "'") {
      escaping = true;
    } else if (quote) {
      if (character === quote) quote = "";
      else token += character;
    } else if (character === "'" || character === '"') {
      quote = character;
    } else if (/\s/.test(character)) {
      if (token) {
        tokens.push(token);
        token = "";
      }
    } else {
      token += character;
    }
  }
  if (escaping) token += "\\";
  if (token) tokens.push(token);
  return tokens;
}
export function normalize(input: string[]): string[] {
  const tokens = [...input];
  let changed = true;

  while (changed && tokens.length) {
    changed = false;
    if (tokens[0].startsWith("\\") && tokens[0].length > 1) {
      tokens[0] = tokens[0].slice(1);
      changed = true;
      continue;
    }
    if (
      tokens[0] === "sudo" ||
      tokens[0] === "env" ||
      tokens[0] === "command"
    ) {
      if (tokens[0] === "command" && ["-v", "-V"].includes(tokens[1])) break;
      const wrapper = String(tokens.shift());
      changed = true;
      while (tokens.length) {
        const next = String(tokens[0]);
        if (
          (wrapper === "sudo" && ["-u", "-g"].includes(next)) ||
          (wrapper === "env" && next === "-u")
        )
          tokens.splice(0, 2);
        else if (
          (wrapper === "env" && !next.startsWith("-") && next.includes("=")) ||
          (next.startsWith("-") && next !== "--")
        )
          tokens.shift();
        else if (next === "--") {
          tokens.shift();
          break;
        } else break;
      }
      continue;
    }
    if (tokens[0].includes("/")) {
      const binary = path.basename(tokens[0]);
      if (BINARIES.has(binary)) {
        tokens[0] = binary;
        changed = true;
      }
    }
  }
  return tokens;
}
export function flags(tokens: string[]): Set<string> {
  const out = new Set<string>();
  for (const t of tokens)
    if (t.startsWith("-") && t !== "-" && t !== "--") {
      out.add(t);
      const base = t.split("=")[0];
      if (base !== t) out.add(base);
      if (LONG_FLAGS[base]) LONG_FLAGS[base].forEach((x) => out.add(x));
      if (SHORT_TO_LONG[base]) out.add(SHORT_TO_LONG[base]);
      if (!t.startsWith("--") && t.length > 2) {
        for (const x of t.slice(1)) {
          const short = `-${x}`;
          out.add(short);
          if (SHORT_TO_LONG[short]) out.add(SHORT_TO_LONG[short]);
        }
      }
    }
  return out;
}
const paths = (t: string[]) =>
  t.slice(1).filter((x) => x !== "--" && !x.startsWith("-"));
const pathArgs = (tokens: string[]) => paths(tokens);
const normalizePath = (value: string): string => value.replace(/^\.\/+/, "");
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
export function match(
  tokens: string[],
  flags: Set<string>,
  rule: Rule,
): boolean {
  if (!tokens.length || (rule.command && tokens[0] !== rule.command))
    return false;
  const tokenSet = new Set(tokens);
  const combinedTokens = new Set([...tokenSet, ...flags]);
  if (
    hasMissingTokens(rule.hasAll ?? [], tokenSet) ||
    hasNoMatchingToken(rule.hasAny ?? [], combinedTokens)
  )
    return false;
  if (
    hasMissingFlags(rule.flagsContain ?? [], flags) ||
    hasExemption(rule.unless, combinedTokens)
  )
    return false;
  const safePaths = rule.unlessPath;
  if (safePaths) {
    for (const p of pathArgs(tokens)) {
      if (p.includes("..")) {
        if (safePaths === true) return true;
        continue;
      }
    }
    if (
      Array.isArray(safePaths) &&
      pathArgs(tokens).length > 0 &&
      !pathArgs(tokens).some((p) => p.includes("..")) &&
      pathArgs(tokens).every((p) =>
        safePaths.some((pattern) => glob(normalizePath(p), pattern)),
      )
    )
      return false;
  }
  return (
    !rule.pathIs ||
    pathArgs(tokens).some((p) => {
      const normalized = normalizePath(p);
      return Array.isArray(rule.pathIs)
        ? rule.pathIs.includes(normalized)
        : normalized === rule.pathIs;
    })
  );
}
const DATA_COMMANDS = new Set(["echo", "printf"]);
const DATA_FLAGS: Record<string, Set<string>> = {
  git: new Set(["-m", "--message", "--grep"]),
  grep: new Set(["-e", "--regexp"]),
  rg: new Set(["-e", "--regexp"]),
  curl: new Set(["-d", "--data", "-H", "--header"]),
  gh: new Set(["-t", "--title", "-b", "--body"]),
};
function sanitize(tokens: string[]): string {
  if (!tokens.length) return "";
  const command = tokens[0];
  let skip = false;
  return tokens
    .map((token, index) => {
      if (skip) {
        skip = false;
        return "_".repeat(token.length);
      }
      if (
        index > 0 &&
        DATA_COMMANDS.has(command) &&
        !token.includes("$(") &&
        !token.includes("`")
      )
        return "_".repeat(token.length);
      if (DATA_FLAGS[command]?.has(token)) {
        skip = true;
        return token;
      }
      return token;
    })
    .join(" ");
}
function segments(s: string): string[] {
  const commandSegments: string[] = [];
  let segment = "";
  let quote = "";
  for (let i = 0; i < s.length; i++) {
    const character = s[i];
    if (character === "'" || character === '"') {
      if (!quote) quote = character;
      else if (quote === character) quote = "";
      segment += character;
      continue;
    }
    if (
      !quote &&
      (character === ";" || character === "|" || character === "&")
    ) {
      if (s[i + 1] === character) i++;
      if (segment.trim()) commandSegments.push(segment.trim());
      segment = "";
    } else segment += character;
  }
  if (segment.trim()) commandSegments.push(segment.trim());
  return commandSegments;
}
const INLINE_SCRIPT_FLAGS: Record<string, string> = {
  bash: "-c",
  sh: "-c",
  zsh: "-c",
  fish: "-c",
  python: "-c",
  python3: "-c",
  ruby: "-e",
  perl: "-e",
  node: "-e",
};
const inline = (tokens: string[]) => {
  const flag = INLINE_SCRIPT_FLAGS[tokens[0]];
  const index = flag ? tokens.indexOf(flag) : -1;
  return index >= 0 ? tokens[index + 1] : undefined;
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
  config: Config = DEFAULT_CONFIG,
  depth = 0,
): Verdict {
  const allow = {
    action: "allow" as const,
    reason: "",
    command,
  };
  if (isAllowed(command, config)) return allow;
  const heredocBody = depth < 1 ? heredoc(command) : undefined;
  if (heredocBody) {
    for (const line of heredocBody.split("\n")) {
      const verdict = evaluate(line.trim(), packs, config, depth + 1);
      if (verdict.action === "block") return verdict;
    }
  }
  const activePacks =
    config.packs.length > 0
      ? packs.filter((pack) => config.packs.includes(pack.id))
      : packs;
  for (const seg of segments(command)) {
    const tokens = normalize(shellSplit(seg));
    if (!tokens.length) continue;
    const commandFlags = flags(tokens);
    for (const pack of activePacks) {
      if (pack.keywords.length && !pack.keywords.includes(tokens[0])) continue;
      for (const rule of pack.rules) {
        if (isBelowThreshold(rule, config.severityThreshold)) continue;
        let matches = match(tokens, commandFlags, rule);
        if (!matches && rule.compiled)
          matches =
            rule.compiled.test(sanitize(tokens)) || rule.compiled.test(seg);
        if (matches && !config.allowRules.includes(rule.ruleId))
          return {
            action: "block",
            ruleId: rule.ruleId,
            reason: rule.reason,
            severity: rule.severity,
            command: seg,
          };
      }
    }
    if (depth < 1) {
      const sub = inline(tokens);
      if (sub) {
        const d = evaluate(sub, packs, config, depth + 1);
        if (d.action === "block") return d;
      }
      const body = heredocBody ? undefined : heredoc(seg);
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
const isAllowed = (command: string, config: Config): boolean =>
  !command.trim() ||
  config.allow.some((value) => command.trim() === value) ||
  config.allowPrefixes.some((value) => command.trim().startsWith(value));
const isBelowThreshold = (rule: Rule, threshold: Severity): boolean =>
  SEVERITY_ORDER[rule.severity] < SEVERITY_ORDER[threshold];
