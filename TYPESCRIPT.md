# TypeScript implementation

HAL now has a standalone TypeScript CLI in `src/`, alongside (and without
changing) the Python implementation. It reads the same `packs/*.yaml` files
and implements the same token normalisation, flag expansion, segment
evaluation, regex fallback, severity threshold, allow lists, and inline
interpreter checks.

Install dependencies and run it with:

```bash
npm install
npm test
npm run build
echo '{"toolInput":{"command":"git push --force"}}' | node dist/cli.js
```

`hal-ts` is the npm binary name so it can coexist with the Python `hal`
command. Hook output is intentionally identical: Copilot receives
`continue`, `permissionDecision`, and `permissionDecisionReason`; Claude
receives `hookSpecificOutput`. Invalid or empty input fails open with exit 0.
The parity tests cover representative decisions and both input protocols.
The Python CLI remains the reference implementation; new rule-pack fields
should be added to both evaluators when extending HAL.
