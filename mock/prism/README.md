# Prism Mock Data

`docs/openapi.yaml` is the canonical API contract. Prism examples are split by domain in `mock/prism/examples/*.json` and injected into a generated Prism spec.

Commands:

```bash
cd frontend
pnpm run mock:build
pnpm run mock:api
pnpm run dev:mock
```

Use `pnpm run dev:with-mock` to run Prism and Vite together.

Keep example files small and domain-focused. Prefer real local names and metadata from `/Users/gx/Documents/Source/huyang_system_data`; generate plausible Chinese-facing examples only where local data is empty or incomplete.
