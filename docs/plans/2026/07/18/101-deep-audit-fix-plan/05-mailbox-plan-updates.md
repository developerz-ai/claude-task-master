# 05 — Mailbox + plan updates: stop losing user messages

> Part of [`overview.md`](overview.md). Depends on: [`01-plan-parsing.md`](01-plan-parsing.md) (validation uses unified parser).

## Bad decisions
Mailbox claims file locking but has none; messages are destructively dequeued before processing; the plan updater trusts raw LLM output and never reconciles the positional task index.

## Files to change
- `mailbox/storage.py:56-176` — **P0**: docstring claims "file-based locking"; every mutation is unlocked load→modify→save. REST/MCP/CLI `add_message` racing orchestrator `get_and_clear` silently destroys or resurrects messages. Fix: reuse `file_lock()` from `core/state.py` (flock on `.claude-task-master/.mailbox.lock`) around load+save in `add_message`, `get_and_clear`, `clear`. Share `_atomic_write_json` from state (07) instead of the duplicated tmp+rename.
- `core/orchestrator.py:519,552-559,647-665` — **P1**: messages dequeued via `get_and_clear` BEFORE processing; if `MessageMerger.merge` or `plan_updater.update_plan` throws (transient API error), user's change requests are permanently lost. Fix: peek → process → clear, or re-enqueue in except paths.
- `core/plan_updater.py:139-164,95-99` — **P1**: `_extract_updated_plan` falls back to the ENTIRE raw model response when markers absent; saved whenever it differs → conversational reply destroys plan.md incl. `[x]` history. Fix: validate extracted plan before save — `parse_tasks` non-empty AND completed count >= previous; else `changes_made=False`, keep old plan; backup plan.md before overwrite.
- `core/plan_updater.py:45-99` + `core/state.py:120` — **P1**: `current_task_index` is positional but the updater rewrites plan.md with no index reconciliation → inserted task shifts everything. Fix: capture current task description before update, re-locate it after via unified parser, set index to its new position (or switch progress tracking to first-unchecked-task).
- `mailbox/merger.py` docstring vs `mailbox/storage.py:154` — priority sorting lives only in `get_and_clear`; `MessageMerger.merge` claims to sort but doesn't. Sort defensively in merge or fix docstring.
- `core/prompts_plan_update.py:30` — change request interpolated inside `**{change_request}**`; multi-paragraph merged requests with `### Change Request N` headers break the bold markup. Move to its own `## Change Request` section.
- `core/planner.py:135-146` (`update_plan_progress` no-op) + `core/plan_updater.py:166-199` (`update_plan_from_messages`, zero callers, drops priority ordering) — delete both.
- Plan-update prompt gets no `max_prs` (see 02/planner) — pass it into `build_plan_update_prompt` so mailbox updates can't blow the `--prs` limit.
- `orchestrator cleanup_on_success` deletes `mailbox.json` with pending messages silently — log dropped count before deletion (see 07).

## Tests
- `tests/mailbox/`: concurrent add vs get_and_clear (two processes/threads with the lock); failed plan update re-enqueues; garbage LLM response leaves plan.md untouched; index reconciliation after insertion.

## Done when
- Kill-tested: no interleaving loses a message; a refusal/prose LLM response can no longer overwrite plan.md.
