# 13 — Prompts: missing injections, contradictions, round-trip contracts

> Part of [`overview.md`](overview.md). Depends on: [`01-plan-parsing.md`](01-plan-parsing.md) (checkbox contract), [`12-sdk-agent-lifecycle.md`](12-sdk-agent-lifecycle.md) (verification parsing).

## Bad decisions (top 5 by leverage — from audit)
1. **context.md is never written** — `ContextAccumulator` instantiated and discarded at `cli_commands/workflow.py:69`; `add_learning`/`add_session_summary`/`save_context` have ZERO callers. Every "Previous Context"/"Context" injection (prompts_planning.py:44, prompts_working.py:105, orchestrator.py:1332, prompts_plan_update.py:47) receives `""` forever — the product's advertised accumulated-learnings feature is silently off.
2. **Non-work sessions wrapped in the create-PR contract** — release verification (`workflow_stages.py:1159`) runs through `run_work_session` with default `create_pr=True`: outer prompt demands "push + PR URL, don't say TASK COMPLETE without it", inner demands verify-only `RELEASE_CHECK: PASS/FAIL/SKIP` → marker omitted → `parse_release_check_result` defaults to "skip", release verification NEVER fails (or model opens a junk PR).
3. **Gitignore claim is false** — prompts_working.py:238,291,329 assert `.claude-task-master/` is auto-gitignored; no code writes .gitignore/`.git/info/exclude`; prompt then says `git add -A` → state dir, logs, mailbox committed into PRs on any repo not already ignoring it.
4. **Planner output contract unpinned** — parser requires exact `## Task List` / `## Success Criteria` headers (agent_phases.py:339,355) but the prompt never says so → criteria.txt silently falls back to "All tasks completed". Also no rule that checkboxes are tasks-only (release-guide example injected into planning literally shows `- [x]` checklists → desyncs parsers, see 01) and no "no blank lines in Release checks block" (extract_pr_release_checks stops at first blank, prompts_release.py:264).
5. **Fix sessions get the wrong mode + no data** — CI/review fixes (`workflow_stages.py:522,902`, `orchestrator.py:1595`) omit `push_only=True` → prompt demands `gh pr create` on an existing PR + "rebase onto main" while `_build_push_only_execution` (prompts_working.py:293) forbids rebase during fixes (fix_session.py:126 passes it correctly, proving intent). Release-fix prompt (`workflow_stages.py:1213`) omits the actual failure `details` from `parse_release_check_result` → 5 blind fix attempts.

## Files to change
- `cli_commands/workflow.py:69` + `core/prompts_verification.py:79` — wire context: after each work session run `build_context_extraction_prompt(session_output, existing_context)` (currently dead) and persist via `ContextAccumulator.add_session_summary()`. Cap injection size (see 07 context_accumulator).
- `core/workflow_stages.py:1159` — release check via query executor directly (as plan_updater.py:126 does) or a verify-only `build_work_prompt` mode (no Execution/PR sections).
- Init path — write `.claude-task-master/` to `.git/info/exclude` at task init; change prompt to `git add -A -- ':!.claude-task-master'`.
- `core/prompts_planning.py:148-151` — STOP section: exact headers `## Task List` / `## Success Criteria`; "checkboxes `- [ ]` ONLY for tasks — plain bullets for criteria and release checks"; "Release checks: consecutive bullets, no blank lines".
- `core/workflow_stages.py:522,902` + `orchestrator.py:1595` — pass `push_only=True, create_pr=False`. Then resolve the rebase contradiction: inline task bodies (`workflow_stages.py:607,660,685`) mandate rebase+force-push while push_only forbids it — pick ONE policy, delete the other text.
- `core/workflow_stages.py:1213-1237` — persist `check_result["details"]`, inject as `## Failed Checks`.
- `core/agent_phases.py:296-312` — verification fallback counts bare substring `"success"` as PASS ("runs successfully but 2 criteria unmet" → exit 0). Remove it; marker-absent output = failure + re-prompt for `VERIFICATION_RESULT: PASS/FAIL`.
- `core/agent_phases.py:345-361` — strip `PLANNING COMPLETE` marker in `_extract_plan`/`_extract_criteria` (currently persisted into criteria.txt/plan.md and re-injected every run). `TASK COMPLETE` instructed in ~10 prompts, parsed nowhere — drop or use.
- `core/orchestrator.py:1332` — context.md passed as `tasks_summary` → renders under "## Completed Tasks". Pass real completed-task summary; context under its own header; inject merged PR numbers.
- `core/prompts_working.py:16,118-139` — dead `file_hints`/`pr_comments` params (no production caller); the valuable "Grep CI logs, never read whole logs" tip is locked inside. Move tip into CI-fix task bodies; delete dead params.
- `core/prompts_working.py:253,297,333` — `echo "msg" >> progress.md` relative path → stray repo-root file committed by `git add -A`; orchestrator regenerates progress.md anyway. Delete the instruction.
- `core/workflow_stages.py:630,884` + `fix_session.py:97` — JSON template shows `"action": "fixed|explained|skipped"` literally; copied pipe-string breaks thread resolution (pr_context.py:399 matches exact values). Pin: `"<one of: fixed, explained, skipped>"`.
- `core/prompts_plan_update.py:30` — change request inside `**{...}**` breaks on multi-paragraph merged requests. Own `## Change Request` section (see 05).
- `mcp/tools.py:1784` — `plan_repo` passes `context=""`, no coding_style/release_guide/max_prs, ignores `model` param. Route through `Planner.create_plan()` (see 10).

## Tests
- `tests/core/test_prompts_release.py` (only prompts module with none — and it has real parsers); round-trip tests: planner-format fixture → `_extract_criteria`/`extract_pr_release_checks`/`parse_tasks` all succeed; verification "successfully but unmet" → FAIL; context accumulation persists across two sessions.

## Done when
- context.md grows across sessions; release check can FAIL; fresh repo PR contains zero `.claude-task-master/` files; every parsed marker is pinned in its prompt.
