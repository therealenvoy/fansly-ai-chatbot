# Domain Docs

## Layout

**Single-context** — one `CONTEXT.md` at the repo root, ADRs in `docs/adr/`.

## Consumer rules

When loading domain context for any skill, read:

1. `CONTEXT.md` at the repo root — the source of truth for architecture, conventions, and domain vocabulary
2. `docs/adr/` — architecture decision records, read when a decision is relevant to the current work

## Writing rules

- `CONTEXT.md` is maintained by the team — update it when architecture or conventions change
- ADRs are immutable once merged — add new ones, don't edit old ones