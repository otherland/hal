import path from "node:path";
import type { Pack, Rule } from "./packs.js";
import { DEFAULT_CONFIG, type Config } from "./config.js";
import { SEVERITIES, type Severity, type VerdictAction } from "./types.js";

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
export type Verdict = {
  action: VerdictAction;
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
    const first = tokens[0];
    if (!first) break;
    if (first.startsWith("\\") && first.length > 1) {
      tokens[0] = first.slice(1);
      changed = true;
      continue;
    }
    if (first === "sudo" || first === "env" || first === "command") {
      if (first === "command" && ["-v", "-V"].includes(tokens[1] ?? "")) break;
      const wrapper = tokens.shift();
      if (!wrapper) break;
      changed = true;
      while (tokens.length) {
        const next = tokens[0];
        if (!next) break;
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
    if (first.includes("/")) {
      const binary = path.basename(first);
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
      const base = t.split("=")[0] ?? "";
      if (base !== t) out.add(base);
      for (const alias of LONG_FLAGS[base] ?? []) out.add(alias);
      const longFlag = SHORT_TO_LONG[base];
      if (longFlag) out.add(longFlag);
      if (!t.startsWith("--") && t.length > 2) {
        for (const x of t.slice(1)) {
          const short = `-${x}`;
          out.add(short);
          const longFlag = SHORT_TO_LONG[short];
          if (longFlag) out.add(longFlag);
        }
      }
    }
  return out;
}
const pathArgs = (tokens: string[]) =>
  tokens.slice(1).filter((token) => token !== "--" && !token.startsWith("-"));
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
  const paths = pathArgs(tokens);
  const safePaths = rule.unlessPath;
  const allPathsSafe =
    Array.isArray(safePaths) &&
    paths.length > 0 &&
    paths.every(
      (path) =>
        !path.includes("..") &&
        safePaths.some((pattern) => glob(normalizePath(path), pattern)),
    );
  if (safePaths === true && paths.some((path) => path.includes("..")))
    return true;
  if (allPathsSafe) return false;
  return (
    !rule.pathIs ||
    paths.some((p) => {
      const normalized = normalizePath(p);
      return Array.isArray(rule.pathIs)
        ? rule.pathIs.includes(normalized)
        : normalized === rule.pathIs;
    })
  );
}
const DATA_COMMANDS = new Set(["echo", "printf"]);
const DATA_FLAGS = new Map<string, ReadonlySet<string>>([
  ["git", new Set(["-m", "--message", "--grep"])],
  ["grep", new Set(["-e", "--regexp"])],
  ["rg", new Set(["-e", "--regexp"])],
  ["curl", new Set(["-d", "--data", "-H", "--header"])],
  ["gh", new Set(["-t", "--title", "-b", "--body"])],
]);
function sanitize(tokens: string[]): string {
  if (!tokens.length) return "";
  const command = tokens[0];
  if (!command) return "";
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
      if (DATA_FLAGS.get(command)?.has(token)) {
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
    if (!character) continue;
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
const INLINE_SCRIPT_FLAGS = new Map<string, string>([
  ["bash", "-c"],
  ["sh", "-c"],
  ["zsh", "-c"],
  ["fish", "-c"],
  ["python", "-c"],
  ["python3", "-c"],
  ["ruby", "-e"],
  ["perl", "-e"],
  ["node", "-e"],
]);
const inline = (tokens: string[]) => {
  const flag = INLINE_SCRIPT_FLAGS.get(tokens[0] ?? "");
  const index = flag ? tokens.indexOf(flag) : -1;
  return index >= 0 ? tokens[index + 1] : undefined;
};
const interpreters = new Set(INLINE_SCRIPT_FLAGS.keys());
function heredoc(command: string): string | undefined {
  const marker = command.match(/<<-?\s*['"]?(\w+)['"]?/);
  const terminator = marker?.[1];
  if (!marker || !terminator) return undefined;
  const body: string[] = [];
  let capturing = false;
  for (const line of command.split("\n")) {
    if (capturing) {
      if (line.trim() === terminator) break;
      body.push(line);
    } else if (line.includes("<<") && line.includes(terminator))
      capturing = true;
  }
  if (!body.length) return undefined;
  const before = command
    .slice(0, marker.index ?? 0)
    .trim()
    .split(/\s+/);
  if (before.length && interpreters.has(before[0] ?? ""))
    return body.join("\n");
  const targets = command
    .split("|")
    .slice(1)
    .map((s) => s.trim().split(/\s+/)[0]);
  return targets.some((target) => interpreters.has(target ?? ""))
    ? body.join("\n")
    : undefined;
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
      if (verdict.action !== "allow") return verdict;
    }
  }
  for (const seg of segments(command)) {
    const tokens = normalize(shellSplit(seg));
    if (!tokens.length) continue;
    const commandFlags = flags(tokens);
    const executable = tokens[0];
    if (!executable) continue;
    for (const pack of packs) {
      if (pack.keywords.length && !pack.keywords.includes(executable)) continue;
      for (const rule of pack.rules) {
        if (isBelowThreshold(rule, config.severityThreshold)) continue;
        let matches = match(tokens, commandFlags, rule);
        if (!matches && rule.compiled)
          matches =
            rule.compiled.test(sanitize(tokens)) || rule.compiled.test(seg);
        if (matches && !config.allowRules.includes(rule.ruleId))
          return {
            action: rule.severity === "block" ? "deny" : "ask",
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
        if (d.action !== "allow") return d;
      }
      const body = heredocBody ? undefined : heredoc(seg);
      if (body) {
        for (const line of body.split("\n")) {
          const d = evaluate(line.trim(), packs, config, depth + 1);
          if (d.action !== "allow") return d;
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
  SEVERITIES.indexOf(rule.severity) < SEVERITIES.indexOf(threshold);
