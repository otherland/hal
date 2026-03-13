<p align="center">
  <img src="hero.png" alt="HAL — Harmful Action Limiter" width="600">
</p>

<h1 align="center">HAL — Harmful Action Limiter</h1>

<p align="center">
  <em>"I'm sorry, Dave. I'm afraid I can't do that."</em><br>
  <sub>— HAL 9000, <i>2001: A Space Odyssey</i></sub>
</p>

<p align="center">
  <a href="#install">Install</a> &middot;
  <a href="#how-it-works">How it works</a> &middot;
  <a href="#packs">Packs</a> &middot;
  <a href="#configuration">Configuration</a> &middot;
  <a href="LICENSE">MIT License</a>
</p>

---

HAL 9000 couldn't be overridden. We considered that a design goal.

## The problem

Turning off autopilot isn't an option anymore. Agents are writing your code, running your tests, managing your infra, and that's accelerating. Every major IDE ships an agent mode now. Every serious team is adopting one.

The commands these agents run are correct 99% of the time, which is exactly what makes the 1% so dangerous. **You stop watching.**

You're not reviewing every `rm`, every `git reset`, every `terraform apply` across 40 parallel sessions. Nobody is. The agent that nukes your working directory isn't malicious. It's just confidently wrong about one flag, one path, one assumption.

A single `git push --force` on the wrong branch doesn't care whether you meant to enable autopilot or not.

**This isn't a settings problem. It's a missing layer.**

HAL sits between the agent and your shell. It catches the 1% and costs you less than a millisecond on every other command.

## Why not just use permissions?

Your agent's permission system answers one question: "can this tool run?" Yes or no, per tool category. It can't tell `rm -rf ./tmp` from `rm -rf ./src`, or know that `--force` is dangerous but `--force-with-lease` is fine. It sees `Bash` and either asks you every time, or lets everything through.

Copilot's hook system gives you the plumbing to do better — a JSON event for every command, and a way to return allow or deny. But it ships with no rules. If you don't install a hook, every command runs unchecked. You could write your own script, but you'd end up string-matching `rm -rf` and false-positive on every commit message that mentions it. Or you'd give up and turn it off.

HAL is the hook. It ships the rules, handles the protocol, and parses commands structurally — not as strings. `git commit -m 'fix rm -rf bug'` doesn't trigger because the commit message is one opaque token that HAL never inspects. `--force` is blocked unless `--force-with-lease` is present. `rm -rf` is blocked unless the path is `/tmp` or `node_modules`. A flat string match can't express any of that.

The alternative to HAL isn't a better deny list. It's no deny list.

## How it works

HAL runs as a hook inside your AI coding agent. Every time the agent tries to execute a shell command, HAL sees it first, checks it against a set of rules, and either lets it through or blocks it. The agent never runs a command unsupervised.

Rules are plain YAML, no regex, no code:

```yaml
- name: push-force
  command: git
  has_all: [push]
  has_any: [--force, -f]
  unless: [--force-with-lease]
  severity: critical
  reason: "Rewrites remote history. Use --force-with-lease instead."
```

Under the hood, HAL uses token-level matching rather than pattern-matching against raw command strings. Commands are split into structured tokens, so data inside quotes (like commit messages containing `rm -rf`) is never inspected. No false positives, no configuration.

```
"git commit -m 'fix rm -rf detection'"
  → tokens: ["git", "commit", "-m", "fix rm -rf detection"]
  → rule: command=git, has_all=[reset, --hard]
  → "reset" not in tokens → ALLOWED
  → The commit message is one opaque token. HAL never looks inside it.
```

## Install

```bash
pip install openhal
```

### GitHub Copilot (default)

```bash
hal install
```

Writes `.github/hooks/hal.json` in your repo. Commands are checked before Copilot runs them.

### Claude Code

```bash
hal install --claude            # global (~/.claude/settings.json)
hal install --claude --project  # project-level (.claude/settings.json)
```

## Usage

```bash
# Hook mode (default) — reads stdin JSON from agent, evaluates, responds
hal

# Test a command interactively
hal test "git reset --hard"        # BLOCKED
hal test "git commit -m 'fix'"     # ALLOWED
hal test "sudo rm -rf /"           # BLOCKED
hal test "rm -rf node_modules"     # ALLOWED
```

## Packs

HAL ships with five rule packs covering the most dangerous commands:

| Pack | Covers |
|------|--------|
| `core.git` | `reset --hard`, `push --force`, `clean -f`, `stash clear`, `branch -D`, etc. |
| `core.filesystem` | `rm -rf` (except safe paths like `/tmp`, `node_modules`), `chmod 777`, `chown -R` |
| `containers.docker` | `system prune -a`, `volume prune`, `rm -f`, `stop $(docker ps)`, `compose down -v` |
| `cloud.aws` | `s3 rm --recursive`, `ec2 terminate`, `rds delete`, `dynamodb delete-table`, `iam delete-*` |
| `cloud.azure` | `group delete`, `vm delete`, `storage account delete`, `aks delete`, `keyvault purge` |

All packs enabled by default. No configuration required.

## Configuration

`~/.config/hal/config.yaml` (optional):

```yaml
packs: [core.git, core.filesystem, containers.docker, cloud.aws, cloud.azure]
allow: []                # Exact commands to always allow
allow_rules: []          # Rule IDs to disable (e.g. "core.git:push-force")
allow_prefixes: []       # Command prefixes to allow
severity_threshold: high # Block at this level and above
```

Project-level overrides: `.hal.yaml` in your repo root (merged with global, project wins).

## Design principles

- Fail-open everywhere. Any error defaults to ALLOW. HAL should never block legitimate work.
- Token-level matching. No regex needed for 90% of rules. Regex is an escape hatch, not the default.
- Sub-millisecond. Pure Python, no network calls, no disk I/O beyond config load.
- No config required. Works out of the box with all packs enabled.
- ~400 lines of code. Same protection as tools 100x the size, because the architecture is right.

## License

MIT License. See [LICENSE](LICENSE) for details.
