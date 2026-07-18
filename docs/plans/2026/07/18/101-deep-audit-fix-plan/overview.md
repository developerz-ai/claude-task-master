# Deep Audit — Bug & Quality Fix Plan

## Goal
Fix every verified defect from an 8-agent parallel audit (logic bugs, prompt failures, security holes, N+1s, resource-lifecycle races, dead code, oversized modules) so claude-task-master is a reliable Claude-SDK orchestrator for big autonomous work.

## Context
- Python 3.12, `uv`, Claude Agent SDK `query()`, Typer CLI, FastAPI REST + MCP server, state in `.claude-task-master/`. Dev loop: `pytest`, `ruff check . && ruff format .`, `mypy .`.
- Every finding below was verified against code by an auditor tracing call sites; re-verify `file:line` at execution time — code moves.
- House rules: 500 LOC/file max, SRP, routing only in `core/config.py`/`core/agent_phases.py`, tests mirror `src` under `tests/`.

## The worst bad decisions (read this first)
| # | Decision | Blast radius |
|---|----------|--------------|
| 1 | Four independent plan.md parsers share one `current_task_index` | wrong task run/marked, non-termination, wrong PR grouping → [01](01-plan-parsing.md) |
| 2 | `context.md` accumulator instantiated then discarded — never written | advertised cross-session learning silently off since forever → [13](13-prompts.md) |
| 3 | Session success hardcoded `True`; `ResultMessage.is_error` never read | budget-killed half-work marked `[x]` complete → [12](12-sdk-agent-lifecycle.md) |
| 4 | Merge on timeout / on "auto-merge scheduled" / on error fallthrough | PRs merged with CI unfinished or unknown state → [03](03-merge-safety-ci.md) |
| 5 | Unauthenticated repo endpoints clone anywhere + execute repo `setup.sh` | remote RCE on `--host 0.0.0.0` installs → [08](08-api-mcp-security.md) |
| 6 | "File-based locking" claimed, none implemented (mailbox, webhooks, session lock) | lost user messages, lost registrations, dual orchestrators → [05](05-mailbox-plan-updates.md)/[07](07-state-durability.md)/[09](09-webhooks.md) |
| 7 | Cross-process control via in-process `threading.Event` + stale in-memory state saves | stop/pause/config from server silently ignored/reverted → [06](06-cross-process-control.md) |
| 8 | Release-fix counter reset by the fix-PR's own merge; safety tracker dead code; no CI-fix cap; default sessions unlimited | unbounded PR/session burn loops → [02](02-orchestrator-loop.md) |
| 9 | Fix/release sessions wrapped in the create-PR work prompt; planner output format never pinned to its parsers | junk PRs, release checks can never fail, empty criteria → [13](13-prompts.md) |
| 10 | Refetch repo info + branch protection every 10s poll tick; single-page GraphQL; no 403/429 backoff | ~2100 gh calls per CI wait; >100-comment PRs invisible → [04](04-github-efficiency.md) |
| 11 | ~2500 LOC confirmed-dead code (conversation, parallel, breaker, pr_cycle, hooks-in-effect) re-exported as live API | maintenance drag, false security confidence → [14](14-dead-code.md) |
| 12 | 19 files over the repo's own 500-LOC rule; REST/MCP/dead-router triplication | the duplication above IS these files → [10](10-rest-mcp-services.md)/[15](15-architecture-splits.md) |

## Plan files (execute in order)
1. [`01-plan-parsing.md`](01-plan-parsing.md) — unify 4 plan parsers; root cause of index bugs.
2. [`02-orchestrator-loop.md`](02-orchestrator-loop.md) — skip-path double-complete, loop caps, dead safety net, branch safety.
3. [`03-merge-safety-ci.md`](03-merge-safety-ci.md) — never merge on timeout/scheduled/error; CI-wait policy.
4. [`04-github-efficiency.md`](04-github-efficiency.md) — N+1s, pagination, backoff, subprocess timeouts.
5. [`05-mailbox-plan-updates.md`](05-mailbox-plan-updates.md) — locking, no message loss, plan-update validation.
6. [`06-cross-process-control.md`](06-cross-process-control.md) — durable control channel, reload-merge-save.
7. [`07-state-durability.md`](07-state-durability.md) — fsync, backups, PID lock, JSONL logs, schema version.
8. [`08-api-mcp-security.md`](08-api-mcp-security.md) — RCE chain, SSRF, auth, event-loop/blocking P0s. **Security.**
9. [`09-webhooks.md`](09-webhooks.md) — wire registry to emitter, retry off-by-one, atomic store.
10. [`10-rest-mcp-services.md`](10-rest-mcp-services.md) — service layer, delete dead routers, one validation path.
11. [`11-cli-config-credentials.md`](11-cli-config-credentials.md) — phase tool defaults, session lock, secret masking, input validation. **Credentials.**
12. [`12-sdk-agent-lifecycle.md`](12-sdk-agent-lifecycle.md) — result-error handling, cancellation, retries, fable effort, RAII.
13. [`13-prompts.md`](13-prompts.md) — context wiring, push-only fixes, gitignore truth, output contracts.
14. [`14-dead-code.md`](14-dead-code.md) — delete ~2500 LOC confirmed dead.
15. [`15-architecture-splits.md`](15-architecture-splits.md) — split all >500 LOC files (move-only, last).
16. [`16-tests-ci-deps.md`](16-tests-ci-deps.md) — top-10 test gaps, flake fixes, dependency upgrades + pins, CI extras.
17. [`17-docs.md`](17-docs.md) — CLAUDE.md/README drift repair; final sweep after all slices.

Parallelizable: 01→02 sequential; 03/04, 05/06/07, 08→09→10, 11, 12→13 are independent tracks; 14→15 last; 16 alongside everything; 17 final. Each slice also updates the docs it invalidates in its own PR.

## Done when
- All P0/P1 findings in slices 01-13 fixed with tests; `pytest`, `ruff check .`, `mypy .` green.
- No unbounded loop with default options; no merge without verified green CI; no unauthenticated mutating endpoint; no lost mailbox message under concurrency kill-tests.
- `context.md` accumulates across sessions; release checks can fail; fable gets max effort.
- Zero files >500 LOC; dead modules gone; deps upgraded and bounded.

## Risks / open questions
- Hooks subsystem (12/14): honor safety hooks or delete honestly — needs owner call; deleting removes an advertised (but currently inert) safety layer.
- Rebase-on-fix vs never-rebase (13): two contradictory policies exist; pick one.
- Circuit breaker: wire the real one or trim to the exception (14).
- SDK upgrade (16) may shift `ResultMessage` fields that 12 depends on — upgrade first, then 12, or pin.
- Sibling repo `../ai-task-master` (TS/Bun port) likely shares several designs (mailbox locking, merge-on-timeout, prompt contracts) — audit it separately from its own repo; not covered here.
- Publish workflows untouched by design — publishes are irreversible.
