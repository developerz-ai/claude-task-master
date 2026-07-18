# 14 — Dead code deletion

> Part of [`overview.md`](overview.md). Depends on: 12 (hooks decision), 13 (prompt wiring decisions). Delete AFTER those decide wire-vs-drop.

## Confirmed dead (import-verified by audit)
- `core/conversation.py` (525 LOC) — `ConversationManager` never instantiated; contains its own stale `ModelType`, duplicate exceptions, None-overwrite bug, missing sonnet_1m. Docstrings in task_runner.py:3,113,220 advertise a "conversation mode" that never happens. **Delete** (+ `tests/core/test_conversation.py`), scrub docstrings.
- `core/parallel.py` (456 LOC) — `ParallelExecutor`/`AsyncParallelExecutor` only re-exported; latent wrong-dependency semantics (deps marked complete at planning time → dependents run after failures). **Delete** (+ test file, `core/__init__.py` re-exports :339).
- `core/circuit_breaker.py` — state machine consumed ONLY by the two dead modules above; live code uses just `CircuitBreakerError` with a hand-rolled counter (agent_query.py:198,275). **Either** wire the real breaker into `AgentQueryExecutor` (then fix 12's HALF_OPEN/CancelledError bugs, derive its threshold and the executor's from one config) **or** trim to the exception. Don't keep both.
- `github/pr_cycle.py` — `PRCycleManager` dead in src (only tests import); weaker semantics (90-min timeout, merge-without-recheck). **Delete** + tests.
- `core/hooks.py` (479 LOC) — dead via `agent.py:94` override (12 decides honor-vs-remove; if remove, delete file + params).
- `core/prompts_verification.py:54,115` — `build_task_completion_check_prompt`, `build_error_recovery_prompt` zero callers (`:79` extraction prompt gets wired by 13). Delete the other two.
- `core/planner.py:135-146` — `update_plan_progress` no-op; `core/plan_updater.py:166-199` — `update_plan_from_messages` unused, drops priority ordering. Delete (also in 05).
- `core/state_pr.py:106-131` — `save_ci_failure` writes files nothing reads. Delete (also in 07).
- `core/checkpoint.py` — memory-only manager, `keep_count` unenforced. Delete unless someone persists it.
- `core/agent_models.py:80-90` — deprecated `ToolConfig` enum, all members alias `[]`. Delete.
- `core/workflow_stages.py:45` — `REVIEW_POLL_TIMEOUT` unused (03 wires or deletes).
- `api/routes_control.py`, `api/routes_config.py` — dead divergent routers (10).
- `core/__init__.py` (350 LOC) — stop re-exporting deleted symbols; shrink.
- `tests/api|core|fixtures/test_fixtures.py` triplicate meta-tests — keep one.

## Steps
1. Land after 12/13 decisions. One PR, deletion-only where possible.
2. `grep -rn` each symbol before deleting (audit verified, re-verify at execution time — code moves).
3. Update CLAUDE.md where it documents deleted surface (pr-{number}/ci/*.txt paths, conversation mode).

## Done when
- ~2500+ LOC gone; `pytest`, `mypy .`, `ruff check .` green; no `core/__init__.py` re-export of removed names.
