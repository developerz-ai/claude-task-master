# 03 — Merge safety + CI wait correctness

> Part of [`overview.md`](overview.md). Depends on: none.

## Bad decisions
Merge decisions trust optimistic/stale signals: timeout ⇒ merge, auto-merge-scheduled ⇒ merged, empty-checks ⇒ no-CI, error ⇒ "continue trying to merge anyway".

## Files to change
- `cli_commands/ci_helpers.py:17,87` + `cli_commands/fix_pr.py:188,219,277` — **P0**: `wait_for_ci_complete` on timeout returns PENDING status; `fix_pr` treats non-FAILURE as fine and merges — PR merged with CI never finished. Also `CI_TIMEOUT = 90*60` vs repo policy 120 min. Fix: return/raise a `timed_out` signal; `merge_pr` treats timeout as block (exit 1) unless `--admin`, mirroring `WorkflowStageHandler._ci_timeout_action`; bump to `120*60`.
- `github/client.py:203-228` + `workflow_stages.py:967` + `fix_pr.py:281` — **P1**: `_try_auto_merge` success (merge *scheduled*) conflated with *merged*: stage set to `merged`, task marked complete, local branch deleted while PR still open; next task branches off a base without the changes. Fix: `merge_pr` returns merged-vs-scheduled; poll `get_pr_status` until `MERGED` (bounded) before advancing.
- `workflow_stages.py:361-370` + `github/client_pr.py:192,389` — **P1**: no-CI fast path fires when checks haven't been created yet (rollup null → PENDING, zero check_details) and `get_required_status_checks` returns `[]` on ANY error incl. 403 rate limit → merges before CI starts. Fix: require min elapsed polls before declaring no-CI; `get_required_status_checks` must distinguish "fetch failed" (raise/None) from "no protection".
- `workflow_stages.py:955-962` — **P1/P2**: `mergeable == "UNKNOWN"` polls forever with no timeout; on `get_pr_status` exception falls through to "Continue trying to merge anyway" — with `admin_merge` this attempts a policy-bypassing blind `--admin` merge. Fix: bound UNKNOWN polling; on exception retry with backoff, never fall through to `merge_pr`.
- `workflow_stages.py:754-761` — pending-check predicate diverges from `ci_helpers.is_check_pending` (StatusContext PENDING has non-None conclusion) → pending external checks (CodeRabbit) don't hold the merge. Reuse `is_check_pending`.
- `workflow_stages.py:45,766` — `REVIEW_POLL_TIMEOUT = 300` defined, never used; reviews governed by the 2h `CI_POLL_TIMEOUT`. Wire it or delete it.
- `cli_commands/fix_pr.py:194-201` — review-bot grace latch (`review_grace_done`) applies only to first green CI; after any fix push, new bot comments race the merge. Reset the latch whenever a fix session pushed.
- `github/client_pr.py:81` — `int(output.split("/")[-1])` on `gh pr create` stdout; any trailing output → ValueError AFTER PR creation → `state.current_pr` unset → duplicate PR next cycle. Use `re.search(r"/pull/(\d+)", ...)`, raise `GitHubError` with raw output on miss.

## Tests
- `tests/cli_commands/` + `tests/core/test_workflow_stages.py`: timeout→block-not-merge; scheduled≠merged; empty-checks grace window; UNKNOWN bounded; grace latch resets.

## Done when
- No code path reaches `merge_pr` from a timeout, an exception, or an unverified auto-merge; `pytest` green.
