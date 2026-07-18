# 02 — Orchestrator work-loop bugs

> Part of [`overview.md`](overview.md). Depends on: [`01-plan-parsing.md`](01-plan-parsing.md).

## Bad decisions
1. Skip-path treated as work-path, so the NEXT task gets marked complete unrun.
2. Every runaway loop (CI-fix, release-fix, review ping-pong) is bounded only by `max_sessions`, which defaults to unlimited — and the safety-net tracker is dead code.

## Files to change
- `core/task_runner.py:251-258` + `core/orchestrator.py:1219-1223` — **P0**: when `run_work_session` hits an already-`[x]` task it increments index and returns "success"; orchestrator then `mark_task_complete` on the NEW index → next task silently marked done, bogus `task.completed` webhook, session_count++. Fix: return status `"skipped_already_complete" | "ran"`; `_handle_working_stage` early-returns on skip; capture `completed_task_index` BEFORE the session runs.
- `core/workflow_stages.py:1070` — **P1**: `handle_merged_stage` resets `release_fix_attempts = 0` on EVERY merge, including release-fix-PR merges → the max-5 cap (line 1183) can never trigger → infinite release-fix loop. Fix: reset only when merged PR is not a release-fix (track `state.in_release_fix`, cleared in `_advance_to_next_task`).
- `core/workflow_stages.py:495-537` — **P1**: `ci_failed → fix → waiting_ci → ci_failed` has no attempt cap. Add `state.ci_fix_attempts`, block after N, reset in `_advance_to_next_task`.
- `core/orchestrator.py:834` + `core/progress_tracker.py:221` — **P1**: `should_abort()` only called when `_current_session is None` → `check_progress` early-returns HEALTHY → LOOP_DETECTED/STALLED can never fire. Fix: evaluate `_task_attempts`/`_last_progress_time` without an active session, or call `should_abort()` inside `_handle_working_stage`.
- `core/progress_tracker.py:237-247` — max_session_duration (30 min) check unreachable (SLOW at 120s returns first). Reorder. Also `estimated_cost` (line 53) uses Sonnet prices labeled Opus — fix rates.
- `core/workflow_stages.py:521-527` (+ `:901`, `orchestrator.py:1594`) — **P1**: fix sessions pass `required_branch=_get_current_branch()` — could be `main` after resume → agent pushes CI fixes to main. Fix: get PR head ref via `get_pr_status` (add `head_branch` to `PRStatus`), checkout it, pass as required_branch.
- `core/orchestrator.py:1458-1471` — `max_ci_fix_attempts = 1` with comment claiming "2 attempts"; actual = 1. Set intended value, fix message.
- `core/workflow_stages.py:283-290` — CI poll timeout uses persisted wall-clock `ci_poll_start_time` → resume after pause instantly times out. Reset on resume/run() entry for waiting stages.

## Small correctness fixes (same slice)
- `orchestrator.py:902-926` — `cleanup_on_success` deletes plan/goal BEFORE `_emit_run_completed` reads them → event always empty. Compute/emit first.
- `orchestrator.py:854` — exit code 2 mapped to `"blocked"` in run.completed; map `{0:"success",2:"interrupted"}`.
- `orchestrator.py:1241` — `completed_tasks + 1` double-count (already marked at :1222). Drop `+1`.
- `orchestrator.py:1066` + `workflow_stages.py:331,737,934` — `pr.merged` webhook + `prs_merged` counter skipped for externally-merged PRs. Emit idempotently in `handle_merged_stage` instead of gating on prior stage.
- `workflow_stages.py:1144` + `orchestrator.py:411,455` — `hasattr(pr_status, "pr_url"/"pr_title")` guards always fail (fields don't exist) → webhooks ship empty PR metadata. Add `title`/`url` to `PRStatus`, populate in `get_pr_status`.
- `workflow_stages.py:103-139` — `_checkout_branch` auto-stashes and never pops/mentions the stash → work silently hidden. Log stash ref loudly + record in context.md, or fail instead.

## Tests
- Extend `tests/core/test_orchestrator.py` + `test_workflow_stages.py`: skip-path no-double-complete; release-fix cap fires; ci-fix cap fires; resume doesn't insta-timeout; run.completed payload non-empty.

## Done when
- No unbounded loop reachable with default options; pre-completed first task doesn't eat the second; `pytest` green.
