# 17 — Docs update: make CLAUDE.md/README match reality

> Part of [`overview.md`](overview.md). Depends on: all fix slices (document what shipped, not what was). Rule: each slice updates the docs it invalidates in its own PR; this slice is the final sweep.

## Known drift (audit-verified)
- CLAUDE.md state-dir tree: documents `pr-{number}/ci/*.txt` + `comments/*.txt`; code writes `debugging/pr/{number}/ci/*.log` (ci_logs.py:335). Fix tree after 07 decides final layout.
- CLAUDE.md phase table (PLANNING/VERIFICATION tool lists) — false until 11 ships restricted `ToolsConfig` defaults; update to match shipped defaults.
- CLAUDE.md "add `.claude-task-master/` to .gitignore" planning claim — code never did it; document the `.git/info/exclude` mechanism from 13.
- CLAUDE.md fallback chain "Opus → Sonnet → Haiku" — single-hop today; align with 12's outcome (chain or honest single-hop).
- CLAUDE.md webhook events section — after 09, document registry-based delivery (`webhooks.json`) vs `--webhook-url`, retry semantics ("0-10 retry attempts" must match fixed loop).
- CLAUDE.md release-fix "max 5 attempts" — true only after 02's counter fix.
- `task_runner.py:3,113,220` docstrings advertising conversation mode — deleted in 14.
- `state.py:598` mixin doc-comment advertising deleted `save_ci_failure` (07/14).
- `doctor`/`debug` docstring claims (checks it doesn't run) — 11.
- Env-var docs: add `CLAUDETM_MODEL_FABLE`, `CLAUDETM_MODEL_SONNET_1M` everywhere env vars are listed (CLAUDE.md, README, `config show --env` table from 11).
- README (repo root): sweep for the same claims (install, commands, API/MCP tool lists incl. renamed params from 10).
- `docs/` tree: check for stale API endpoint/MCP tool references after 10's service extraction.

## Steps
1. After slices land: grep CLAUDE.md/README/docs for every symbol/path/claim touched by 01-16; fix each against code, not memory.
2. Verify examples still run (`claudetm start ... --prs`, server curl examples).
3. Keep CLAUDE.md philosophy section intact — this is drift repair, not rewrite.

## Done when
- Every path, table, env var, and behavioral claim in CLAUDE.md/README traceable to current code; no reference to deleted modules.
