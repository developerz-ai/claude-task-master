# 01 — Unify plan parsing (root cause of task-index bugs)

> Part of [`overview.md`](overview.md). Depends on: none. **Do this first — 5+ downstream bugs collapse into it.**

## Bad decision
Four independent plan.md parsers index the same `state.current_task_index`:
- `task_runner.py:487,507,525` — `startswith("- [ ]")/("- [x]")`: lowercase-only, exact spacing, counts checkboxes inside `**Release checks:**` sections.
- `task_group.py:209` — regex `^-\s*\[([ xX])\]`: accepts `[X]`, skips release-check lines.
- `state_file_ops.py:208` (`_parse_plan_tasks`, used by `validate_resume`, `/status`, API routes) — third copy, same `[X]` gap.
- `orchestrator.py:365` (`_get_completed_tasks`) — inline regex `^- \[x\]`, misses indented + `[X]`.

Consequences: agent writes `- [X] Done` → naive parser drops the line → every index shifts → `mark_task_complete` ticks the wrong line, `is_all_complete` never terminates or terminates early, tasks land in wrong PR group, progress counts wrong (`_get_total_tasks` vs `_get_completed_tasks` use different parsers).

## Files to change
- New `src/claude_task_master/core/plan_parsing.py` — single owner of parse/mark/count. Move `parse_tasks_with_groups` + friends from `task_group.py` here (or keep in task_group and re-export; either way ONE regex).
- `core/task_runner.py:487-548` — delete `parse_tasks`/`is_task_complete`/`mark_task_complete`/`is_all_complete` string logic; delegate to unified parser. `mark_task_complete` must locate the line via the same regex and do regex substitution (handles `- [  ]`, `-[ ]`).
- `core/state_file_ops.py:208` — `_parse_plan_tasks` delegates.
- `core/orchestrator.py:352-369` — `_get_total_tasks`/`_get_completed_tasks` delegate.
- `core/task_group.py:43-59` — also fold duplicate complexity→model map into `agent_models.py` (delegate, one source; drift currently causes `ValueError` at session start).

## Steps
1. Extract `plan_parsing.py`: `parse_tasks(plan) -> list[ParsedTask]` (index, text, is_complete, group, is_release_check), `mark_complete(plan, index) -> str`, `count_complete(plan) -> tuple[int,int]`. Case-insensitive `[xX]`, tolerant spacing, release-check exclusion.
2. Rewire the four call sites above. `run_work_session` (task_runner.py:248) and `_get_group_context` (task_runner.py:184) must consume the SAME list.
3. `is_all_complete`: return `False` (or raise `NoPlanFoundError`) when `load_plan()` is None/empty — today returns `True` → bogus success + `cleanup_on_success` wipes state (task_runner.py:543).
4. Fix `validate_for_resume` (state.py:568): bounds check is skipped when plan parses to zero tasks.

## Tests
- `tests/core/test_plan_parsing.py` — property-style: all former call sites agree on `[X]`, `-  [x]`, indented, release-check checkboxes, empty plan.
- Run: `pytest tests/core/ && ruff check . && mypy .`

## Done when
- One parser module; grep shows no `startswith("- [")` outside it. `- [X]` plans complete correctly end-to-end.
