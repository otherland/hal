# TypeScript implementation

HAL is implemented as a TypeScript CLI in `src/`. It reads the existing
`packs/*.yaml` files
and implements the same token normalisation, flag expansion, segment
evaluation, regex fallback, severity threshold, allow lists, and inline
interpreter checks.

Install dependencies and run it with:

```bash
npm install
npm test
npm run build
echo '{"toolInput":{"command":"git push --force"}}' | npx hal
```

The npm binary is `hal`. Hook output is intentionally identical: Copilot receives
`continue`, `permissionDecision`, and `permissionDecisionReason`; Claude
receives `hookSpecificOutput`. Invalid or empty input fails open with exit 0.
The focused tests cover representative decisions, heredocs, and both hook
protocols. New rule-pack fields should be covered by the TypeScript evaluator
and a focused test when extending HAL.
