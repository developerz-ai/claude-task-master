# CLAUDE.md

Project instructions for Claude Code when working with Claude Task Master.

## Project Overview

Autonomous task orchestration system that uses Claude Agent SDK to keep Claude working until a goal is achieved. Uses OAuth credentials from `~/.claude/.credentials.json` for authentication.

**Core Philosophy**: Claude is smart enough to do work AND verify it. Task master keeps the loop going and persists state.

### Key Capabilities

- **Autonomous Execution** - Runs until goal achieved or needs human input
- **PR-Based Workflow** - All work flows through pull requests for review
- **CI/CD Integration** - Handles CI failures and review comments together in one step
- **Mailbox System** - Accept dynamic plan updates while working (REST API, MCP, or CLI)
- **Multi-Instance Coordination** - Multiple claudetm instances can communicate via mailbox
- **State Persistence** - Survives interruptions, resumes where it left off
- **Resume with Message** - Update the plan mid-execution with `claudetm resume "message"`

## Installation

### Global Install (Recommended for usage)
```bash
# Install globally via uv tools
uv tool install /path/to/claude-task-master

# Or reinstall after changes
uv tool install --force --reinstall /path/to/claude-task-master

# Verify installation
claudetm doctor
```

### Development Install (For contributing)
```bash
# Clone and setup
uv sync --all-extras             # Install dependencies in .venv
./scripts/setup-hooks.sh         # Install git pre-commit hooks
uv run claudetm doctor           # Check system (runs from .venv)
```

## Quick Start

```bash
# Usage (after global install)
cd <project-dir>
claudetm start "Your task here" --max-sessions 10
claudetm start "Add feature" --prs 1         # Limit to 1 PR
claudetm start "Implement API" --prs 3 -n 10 # Max 3 PRs, 10 sessions
claudetm start "Fix bug" --budget 5.00       # $5 per session cap
claudetm status           # Check progress
claudetm plan             # View task list
claudetm clean -f         # Clean state

# Or with uv run (development mode)
uv run claudetm start "Your task here"
```

## Development

```bash
pytest                    # Run tests
ruff check . && ruff format .  # Lint & format
mypy .                    # Type check
```

## Releasing

```bash
# 1. Update version in all places (CI's verify job checks the first three):
#    - pyproject.toml (version = "X.Y.Z")
#    - src/claude_task_master/__init__.py (__version__ = "X.Y.Z")
#    - bin/claudetm AND src/claude_task_master/bin/claudetm (SCRIPT_VERSION="X.Y.Z")
#      Two copies; the packaged one ships. It is what `claudetm --version` prints
#      first, so a stale value reports a release the user is not on.
#    - CHANGELOG.md (add entry, update links at bottom)

# 2. Commit and tag
git add -A && git commit -m "chore: Release vX.Y.Z"
git tag vX.Y.Z
git push origin main --tags

# 3. CI publishes to PyPI automatically on tag push
# 4. Install from PyPI after release:
uv tool install claude-task-master --force --reinstall
```

## Architecture

**Components** (Single Responsibility):
1. **Credential Manager** - OAuth from `~/.claude/.credentials.json` (nested `claudeAiOauth` structure)
2. **State Manager** - Persistence to `.claude-task-master/`
3. **Agent Wrapper** - Claude Agent SDK `query()` with real-time streaming
4. **Planner** - Planning phase (read-only tools)
5. **Plan Updater** - Updates existing plans with change requests (for `resume "message"`)
6. **Work Loop Orchestrator** - Execution loop with task tracking, mailbox checks
7. **Mailbox** - Inter-instance communication for dynamic plan updates
8. **PR Context Manager** - CI failures + review comments fetched together
9. **Logger** - Consolidated `logs/run-{timestamp}.txt`

**Tool Configurations by Phase**:
| Phase | Tools | Purpose |
|-------|-------|---------|
| PLANNING | Read, Glob, Grep, WebFetch, WebSearch | Explore codebase + research web for documentation, output plan as TEXT (orchestrator saves to plan.md) |
| VERIFICATION | Read, Glob, Grep, Bash | Run tests/lint to verify success criteria |
| WORKING | All tools | Implement tasks with full access |

These sets are a strong **default, not enforcement**: `allowed_tools` is the SDK's *auto-approve* list, and restricting what exists needs `tools=`, which claudetm never passes while running `permission_mode="bypassPermissions"`. So a planning session is read-only by convention and prompt, not by a sandbox. The same fact is why the WORKING phase can spawn subagents with no code change at all — `tools.working` defaults to `[]`, i.e. unrestricted.

**Task Complexity Levels** (for dynamic model routing + effort-based thinking):
| Complexity | Tag | Model | Effort | Use Case |
|------------|-----|-------|--------|----------|
| CODING | `[coding]` | Opus 5 (1M) | max | Complex implementation tasks, new features, intricate logic |
| QUICK | `[quick]` | Haiku | low | Simple fixes, configuration changes, small tweaks |
| GENERAL | `[general]` | Sonnet | medium | Tests, documentation, moderate refactoring, balanced tasks |
| DEBUGGING_QA | `[debugging-qa]` | Sonnet 1M | high | CI failures, bug tracing, visual QA, log analysis (1M context) |

When uncertain, default to `[coding]` (uses the smartest model). The smartest tier is **Claude Opus 5** (`claude-opus-5`) — see the `opus` default in `ModelConfig` in `core/config.py`. `context_windows.opus` defaults to `1_000_000` because Claude Code upgrades Opus to 1M automatically on Max/Team/Enterprise (on Pro that upgrade is billed to usage credits — set `200000` there). Do **not** write the model id as `claude-opus-5[1m]`: the `[1m]` suffix is a Claude Code alias convention, accepted by the CLI but a `404 not_found_error` on `GET /v1/models`, so it is not a portable model string. The window is configured via `context_windows.opus`, not a suffixed model id.

`context_windows` is **currently inert** — nothing reads it. `get_context_window`, `MODEL_CONTEXT_WINDOWS` and `DEFAULT_COMPACT_THRESHOLD_PERCENT` (`core/agent_models.py`) are referenced only by the re-exports in `core/__init__.py`; no value derived from `config.context_windows` reaches `ClaudeAgentOptions` or any compaction logic, so setting it changes no behaviour today. The config surface stays (config key, `CLAUDETM_CONTEXT_*`, per-profile overrides) and the defaults are written for its *intended* meaning: an auto-compact threshold, never a grant of a larger window — over-stating it would compact too late and overflow the session; under-stating it compacts early, which is harmless. On that reading `sonnet` stays at `200_000`: on a subscription the 1M Sonnet window is the paid extra, so it is opt-in rather than assumed. An opt-in `fable` tier (**Claude Fable 5**, `claude-fable-5`, premium-priced) exists alongside it — configured via the `"fable"` config key or `CLAUDETM_MODEL_FABLE`, mirroring Claude Code's `ANTHROPIC_DEFAULT_FABLE_MODEL`. No complexity level routes to it by default (2x Opus pricing); users opt in via `CLAUDETM_MODEL_FABLE=claude-fable-5` or by passing the `fable` model key explicitly. The `sonnet_1m` tier uses Sonnet with 1M context (e.g., `claude-sonnet-5` configured as `CLAUDETM_MODEL_SONNET_1M` for log analysis). Fallback: Fable → Opus → Sonnet → Haiku.

**Fallback Models**: If primary model is unavailable, auto-fallback: Fable → Opus → Sonnet → Haiku.

**State Directory**:
```
.claude-task-master/
├── goal.txt              # User goal
├── criteria.txt          # Success criteria
├── plan.md               # Tasks (markdown checkboxes, with per-PR release checks)
├── state.json            # Machine state
├── progress.md           # Progress summary
├── context.md            # Accumulated learnings
├── coding-style.md       # Coding style guide (generated from CLAUDE.md)
├── release.md            # Release guide (generated by probing deploy infrastructure)
├── mailbox.json          # Pending messages for plan updates
├── logs/
│   └── run-*.txt         # Last 10 logs kept
└── debugging/
    └── pr/
        └── {number}/     # PR-specific context
            ├── ci/
            │   └── *.log # CI failure logs (chunked, ~20KB per file)
            └── comments/ # Review comments
```

## Exit Codes

- **0 (Success)**: Tasks done, cleanup all except logs/, coding-style.md, and release.md, keep last 10 logs
- **1 (Blocked)**: Need intervention, keep everything for resume
- **2 (Interrupted)**: Ctrl+C, keep everything for resume

## Key Implementation Details

### Credentials Loading
- File structure: `{"claudeAiOauth": {accessToken, refreshToken, expiresAt, ...}}`
- `expiresAt` is milliseconds (int), divide by 1000 for datetime
- Agent SDK auto-uses OAuth from credentials file
- **Token refresh is handled automatically by Claude Agent SDK/binary** - we don't manually refresh
- If auth fails, re-run `claude` CLI to re-authenticate

### Agent SDK Integration
- Use `query()` with `ClaudeAgentOptions(allowed_tools=[], permission_mode="bypassPermissions")`
- Message types: `TextBlock`, `ToolUseBlock`, `ToolResultBlock`, `ResultMessage`
- The working directory is **passed** to the SDK as `cwd=str(self.working_dir)` in `ClaudeAgentOptions`; the process never `chdir`s (`core/agent_query_execute.py`). A global chdir would race concurrent queries in server mode — and it is exactly what makes concurrent subagents inside one session safe. The directory is checked for existence first so a missing path fails clearly instead of as a cryptic SDK error
- Stream output real-time: tool use and results print via `core/console.py` as ANSI-coloured `[claude HH:MM:SS N/M] …` lines (`Using tool: <name> <detail>`, then `Tool completed` / `Tool error`). No emoji anywhere in the printer

### Task Management
- Parse `- [ ]` and `- [x]` from plan.md
- Check `_is_task_complete()` before running (skip if [x])
- Mark complete with `_mark_task_complete()`
- Advance `current_task_index` to the last task the session actually completed, and save state. Treat it as the loop's **cursor**, not a counter that only goes up: several sites move it forward (the per-task advance, the group-shipping path, post-merge), one deliberately **rewinds** it so a skipped task still closes its group (`loop_working_stage`), and plan updates reconcile it against the rewritten plan (mailbox processing and `resume "message"`). Hive fan-out does not touch this: a session that split its task across workers still advances the cursor by exactly one task

### Work Completion Requirements

What a task owes depends on where it sits in its PR group — `should_create_pr = state.options.pr_per_task or is_last_in_group` (`core/task_runner_session.py`):

- **Not the last task of its group** — the default mode, and most tasks — owes a **commit only**. The prompt is `_build_commit_only_execution` ("DO NOT create PR yet"), and its completion block requires a commit hash and nothing else. Pushing early would open a PR for half a group.
- **The last task of its group, and every task under `--pr-per-task`** owes all three: commit with a descriptive message, `git push -u origin HEAD`, `gh pr create …` — and must report both the commit hash AND the PR URL.

Either way the agent's report is not the evidence. The orchestrator checks the repository: a session that leaves a dirty tree did not finish, whatever it claimed (see *Unfinished sessions*).

### CLI Commands
All commands check `state_manager.exists()` first:
- `start`: Initialize and run planning → work loop. Flags worth knowing: `--admin`, `--sync-before-merge` (both opt-in), `--no-parallel` (turns off hive fan-out, which is on by default — see below)
- `resume`: Resume paused task, optionally with message to update plan first
- `status`: Show goal, status, session count, options
- `plan`: Display plan.md with markdown rendering
- `logs`: Show last N lines from log file
- `progress`: Display progress.md
- `context`: Display context.md
- `merge-pr`: Monitor PR, fix CI/comments/conflicts, then merge (alias: `fix-pr`)
- `clean`: Remove .claude-task-master/ with confirmation
- `mailbox`: Show mailbox status
- `mailbox send "msg"`: Send message to mailbox
- `mailbox clear`: Clear pending messages
- `profile`: Manage auth profiles (`add`/`list`/`use`/`show`/`remove`/`login`)
- `update`: Self-update from PyPI via `uv tool install --force --reinstall` (pipx fallback); `--check` only reports whether a newer version exists

### Profiles (Multi-Account / Custom Endpoints)
- Profiles isolate credentials so multiple Claude subscriptions (or a custom Anthropic-compatible endpoint) can be used without colliding on the global `~/.claude/.credentials.json`
- Two types: `oauth` (isolated `CLAUDE_CONFIG_DIR` per profile under `~/.claudetm/profiles/<name>/`) and `api-key` (injects `ANTHROPIC_API_KEY`/`ANTHROPIC_BASE_URL`, e.g. z.ai/GLM)
- Registry at `~/.claudetm/profiles.json` (override base dir with `CLAUDETM_HOME`); active profile is a single pointer, overridable per-run via `CLAUDETM_PROFILE`
- **`default` is reserved** (`DEFAULT_PROFILE_NAME`) for the ambient Claude Code login at `~/.claude` / `CLAUDE_CONFIG_DIR` — the credentials used when no profile is selected. It has no registry entry, so `use("default")` *clears* the pointer and returns None, and `resolve_active` maps the name to None instead of raising. `add` rejects it; a pre-existing registry profile of that name still shadows the built-in everywhere (lookups check the registry first)
- The active profile's env is injected at the SDK subprocess boundary (`core/agent_query_execute.py`); `CredentialManager` reads the active oauth profile's config dir, and short-circuits the OAuth file check for `api-key` profiles
- Different accounts run in parallel safely (per-profile creds dir + per-project state); running the *same* subscription twice can trigger OAuth refresh-token rotation — use a distinct profile per concurrent run

### Mailbox System
- Messages stored in `.claude-task-master/mailbox.json`
- Checked after each task completion by orchestrator
- Multiple messages merged with priority ordering (urgent → low)
- Merged message triggers plan update via `PlanUpdater`
- REST: `POST /mailbox/send`, `GET /mailbox`, `DELETE /mailbox`
- MCP: `send_message`, `check_mailbox`, `clear_mailbox` tools

### Resume with Message
- `claudetm resume "change"` updates plan before resuming
- Uses `PlanUpdater` to integrate change request into existing plan
- Preserves completed tasks, modifies pending tasks as needed

### Unfinished sessions (a session that stops mid-task never counts as done)

A work session can end without finishing: the SDK cuts it off (`error_max_turns`, budget cap, `error_during_execution`), or the agent ends its turn waiting on a backgrounded check and the harness kills it. Neither looks like a failure — the second one is a perfectly clean `end_turn` — so the loop used to check the task `[x]`, advance to `pr_created`, find no PR and a dirty tree, and block for a human.

Two independent signals decide whether a session satisfied its contract (`_LoopWorkingStageMixin._session_unfinished_reason`):

- **the SDK's terminal result** — an error result surfaces as `run_work_session` returning `"ran_incomplete"` (`task_runner_session`), derived from `ResultMessage.is_error`
- **a clean working tree** — the session's own contract is "commit your work", so leftover changes mean it stopped mid-task. Probed in the project dir, not the process cwd. A failed probe (no git, not a repo, timeout) is never read as unfinished

Unfinished → the task is **not** checked off and the same task re-runs, with a `**Retry N**` note in its prompt telling it the leftover diff is its own work to finish, not redo. **That note is driven by the working tree, not by the counter** (`_TaskRunnerSessionMixin._continuation_note`): `task_finish_attempts` is only incremented after the orchestrator *observes* an unfinished session, which a killed process never gets to do. A run that dies mid-session — Ctrl+C, OOM, the machine going down — used to resume into a plain prompt with a large uncommitted diff and no explanation, and the agent could redo the work or throw it away. A dirty tree entering a work session now says so on its own, names the leftover paths (capped at 40 lines / 2000 chars, truncation marked), and forbids discarding them: `git checkout --`/`restore`/`stash`/`reset --hard`/`clean` are unrecoverable, and starting over from a clean tree is the one always-wrong outcome. Bounded by `MAX_TASK_FINISH_ATTEMPTS` (2, `state.task_finish_attempts`); after that the task is checked off anyway and the PR stage takes over — the finish session below can still ship a dirty tree, so a stubborn task must not deadlock the run. Retries burn sessions, so `--max-sessions` still bounds everything.

**The terminal result must survive the CLI's exit code.** After an error result the CLI exits non-zero *on purpose* (for shell consumers), and the SDK turns that trailing `ProcessError` into a bare `Exception("Claude Code returned an error result: <subtype>")` raised from the *next* `__anext__()`. Raising it buried the outcome the `ResultMessage` had already reported and killed the whole run — one `Connection closed mid-response` blip ended a 22-task unattended run at task 1. `_execute_query` now tracks `terminal_result_seen`: once a `ResultMessage` arrives the session is over, so any later stream error or stall closes the stream and returns the accumulated text, and the caller derives `ran_incomplete` from `is_error` as designed. The guard is scoped to *post-terminal* teardown — an error with no terminal result behind it still reaches the retry path.

Relatedly, an unclassified `QueryExecutionError` (a CLI crash whose text carries no keyword `_classify_api_error` recognises) is no longer fatal on sight: it retries under the same failure budget as a connection error (`rate_limit_config.max_retries`), and only a persistent one raises `ConsecutiveFailuresError`.

### Usage limits are an account condition, never a task failure

When the subscription exhausts its window, the CLI answers every query in seconds with only
`You've hit your session limit · resets 1pm (America/Bogota)` and an error terminal result. Before
this was recognized, one limited run burned both retry attempts of task after task in ninety
seconds, **checked four untouched tasks off as complete** (the exhausted-budget fallback), spent the
PR-recovery finish budget the same way, and blocked with a message that never named the cause.

Two layers now handle it (`core/usage_limit.py`):

- **The agent phase layer waits limits out.** Every query — work, fix, finish, planning,
  verification, release check, learnings extraction, coding-style/release-guide generation — routes
  through `run_query_riding_out_usage_limits`: a refused query parses the stated reset time
  (clock-with-timezone or the API's epoch suffix), sleeps until it (interruptibly, Escape/SIGINT
  honored within seconds), and re-runs. Callers never see the refusal unless the wait was
  interrupted or `CLAUDETM_USAGE_LIMIT_MAX_WAITS` (48) consecutive waits ran out. A single wait is
  capped at `CLAUDETM_USAGE_LIMIT_MAX_WAIT_SEC` (6h, misparse protection); an unparseable reset
  falls back to `CLAUDETM_USAGE_LIMIT_DEFAULT_WAIT_SEC` (30 min) polls.
- **The working stage refuses to charge a refusal to the task.** A refused session that still leaks
  through consumes no `task_finish_attempts`, is never checked off (not even by the exhausted-budget
  fallback), heartbeats the tracker (the progress clock was stamped at session *start*, possibly
  hours earlier), and simply re-enters the working stage. Context accumulation likewise skips
  limit-notice output instead of distilling it into context.md.

Detection scans only the output **tail** (a refused session's whole output IS the notice), so a real
session that merely quotes limit phrasing mid-way — claudetm working on claudetm — is not misread.

### Undelivered fix sessions (push-only stages)

A CI-fix, review-fix or conflict session promises the same two things: **commit** the work, then **push** it so CI re-runs against the fix. Neither was verified — the agent's own report is not evidence, and a session killed mid-turn reports success. Both are now checked against the repository (`_GitOps._fix_session_unfinished_reason`):

- **uncommitted changes** — the session stopped mid-fix. This also breaks the merge outright: `gh pr merge` checks branches out and refuses on a dirty tree
- **unpushed commits** — the fix exists locally only, so the next `waiting_ci` poll reads the *previous* push's green CI as this fix's and merges the PR without the fix

Undelivered → the stage repeats instead of advancing, bounded by `MAX_FIX_FINISH_ATTEMPTS` (2, `state.fix_finish_attempts`), then blocks. Ordering matters in `addressing_reviews`: the check runs **before** `post_comment_replies`, because resolving the threads is what tells the rest of the workflow the review is handled. A CI-fix that delivered nothing refunds `ci_fix_attempts` — that counter bounds "the fix didn't work", not "no fix was produced".

`ready_to_merge` additionally refuses to call `gh pr merge` on a definite dirty tree, reporting the pending files instead of the raw git checkout error. Same guard on the other two merge sites: the verification fix-PR path (`loop_verification`) and the `merge-pr`/`fix-pr` CLI.

The CLI carries its own copy of the contract check (`fix_session.fix_session_undelivered_reason`) because `fix-pr` runs without a stage handler — `run_fix_session` had the review stage's bug verbatim, resolving threads for a fix that never reached the PR.

**Planning is covered by the same rule.** `run_planning_phase` reports `success`/`subtype` like `run_work_session`, and the planner refuses to persist a plan from a cut-off session: every later stage treats `plan.md` as the whole job, so a task list that stops halfway is worse than none. `PlanUpdater` was already safe here — it validates the result parses to real tasks, preserves every completed task, and backs up before overwriting.

Fail-open vs fail-closed is deliberate. `_porcelain_status()` returns three states (`""` / dirty / `None` = unreadable). `_has_uncommitted_changes()` folds unreadable into dirty (fail **closed**) for pushing and PR-opening; the fix probe and merge guard act only on a *definite* dirty tree (fail **open**), since looping a session over a repo you cannot measure is worse than deferring to `gh`.

### Missing-PR recovery (dirty tree included)

`pr_created` with no PR on the branch self-heals rather than blocking (`core/stages/pr_recovery.py`):

- **clean tree, commits ahead of base** → the orchestrator pushes and opens the PR itself
- **clean tree, nothing ahead** → nothing to ship; stage advances to `merged`
- **dirty tree** → a bounded *finish session*: an agent verifies, commits, pushes and opens the PR for the whole group. Bounded by `MAX_PR_FINISH_ATTEMPTS` (2, `state.pr_finish_attempts`). The stage stays `pr_created`, so the next cycle either detects the PR the session opened or — tree now clean — takes the deterministic push+create path
- **still blocks** for what genuinely needs a human: sitting on the base branch, a failed base comparison, a failed push/`gh pr create`, a crashed finish session, or a tree still dirty after the attempt budget

Both counters reset on task advance, like `ci_fix_attempts`.

### What ends a PR group (the only thing that opens a PR)

Outside `--pr-per-task`, a PR is opened for exactly one reason: the task just finished was the **last of its group** (`is_last_task_in_group` → `pr_created`). Everything else runs commit-only. Two ways that test used to answer "no" forever, both of which produce the same silent failure — tasks completing, commits stacking on an unpushed local branch, zero PRs:

- **Groups must be contiguous.** Group membership comes from `### PR <n>: …` headings, and a planner that restates its task list (draft → verification → "reissuing the corrected plan") writes the same heading two or three times. Keying groups by heading number alone folded the restatements into one group with a non-contiguous index set, so the group did not "end" until its *final* restatement. A repeated heading now opens a new instance — `pr_10` → `pr_10#2` (`_new_group_id`, `core/task_group.py`) — which keeps each group's indices a contiguous run. Re-entering the heading already current is not a new instance. `TaskGroup.pr_number` strips the suffix.
- **A skipped task still closes its group.** A task already `[x]` runs no session, and the skip path returned without checking the boundary — stranding commits that were already on the branch (a resume, or a task checked off by `MAX_TASK_FINISH_ATTEMPTS`). It now rewinds the index `run_work_session` advanced and enters `pr_created`; `_PRRecovery` opens the PR or closes the group out with no agent session. Skipped on the base branch — nothing is committed there and the PR stage would block.

A triplicated `plan.md` still runs its work N times; the parser only guarantees each block ships. If the task count looks 2–3× too large, check for repeated `### PR n:` headings before blaming the loop.

### Hive mode — the task is the unit of parallelism (`--parallel`, on by default)

- **The parallelism lives inside one task, not across tasks.** The loop is unchanged: one work session per plan task, one task checked off per session, `TASK COMPLETE` reported exactly as before. What `--parallel` adds is that the agent running that session is a **lead** — it may cut *its own single task* into pieces with **disjoint write sets** and hand each piece to a `hive-worker` subagent, doing everything that overlaps itself. There is no batching, no manifest and no new bookkeeping; the orchestrator cannot tell a fanned-out session from a solo one except by what lands in the tree.
- **On by default** (`TaskOptions.parallel`, default True; `--no-parallel` to keep every session strictly single-agent, `claudetm config-update --no-parallel` mid-run). Parallel is the default because the *decision* is free — the lead only spends anything if it finds real seams.
- **Workers exist to do real, big work.** The brief's calibration is "few LARGE self-contained pieces" — a whole module, a feature slice with its own tests and docs, a subsystem sweep — never scattered micro-edits. Each worker carries its own turn budget (`AgentDefinition.maxTurns`, `CLAUDETM_HIVE_WORKER_MAX_TURNS`, default 200 via `hive_worker_max_turns()`) sized for that, and the worker contract tells it to finish its piece completely (code, tests, docs) and never to spawn agents of its own. A project agent can pin its own budget with `max_turns:` in its frontmatter.
- **The lead sizes its own team; the orchestrator never counts for it.** Nothing outside the session can tell how big a task is before it runs, so how many workers a task deserves is a judgement made in the prompt (`core/prompts_working_hive.py`), not a number computed from the plan. **Two or more workers, or none — never exactly one.** A lone worker buys no speed (the only thing fan-out is for): full cold start, the lead idle and blind to its tool calls, and everything still to verify on disk. Zero is the right answer for anything small enough that the cold start costs more than the work.
- **The project's own `.claude/agents/` specialists come first; `hive-worker` is the fallback.** `list_project_agents()` (`core/subagents.py`) surfaces each project agent's name and description in the fan-out brief; the lead matches every piece against them FIRST and dispatches the matching specialist (`subagent_type: <name>`) under the same rules — generic `hive-worker` takes only the pieces no specialist fits (and everything, when the project defines none). Read per work session, so agents added mid-run are picked up.
- **Dispatch is optimized, not just permitted.** All independent pieces go out in a single message (concurrent, never in waves), the lead works its own kept pieces while workers run instead of idling, and every brief carries four things: the work in full, the exclusive file set, which other workers are live, and the context the lead already gathered (key excerpts, conventions, the API surface to conform to) so the worker's cold start is not spent re-deriving it.
- **The team is sized against the machine too, not just the task.** `hive.describe_machine()` measures the box the run landed on — CPU model and cores, load average, available/total RAM, free disk — and the figures are interpolated into the fan-out brief, so the lead takes the smaller of "disjoint seams my task has" and "agent processes this box can actually run". Best-effort and dependency-free (`/proc`, `shutil.disk_usage`); a platform that reports nothing omits the paragraph, because sizing a team is never a reason to fail a run.
- **The seam is the API, not the path.** Disjoint file sets are necessary and not sufficient: a piece that renames an export, changes a signature or edits a shared type breaks every file importing it, *including files no worker owns*. The lead lists, per piece, what it changes that something else reads, and either pulls every caller into that set or keeps the piece itself. (Observed live: one worker renamed a field across the files it owned, an unowned file kept the old name, and all six workers reported success.)
- **Whether workers may run checks at all is the lead's call, stated in each brief.** Concurrent scoped test/lint runs are a property of *the project* — a shared database or fixture schema, a fixed port, one build or coverage directory, a lock — so the lead looks, decides, and writes the exact scoped command into each brief or explicitly "none". Either way it runs the full gate once at the end. Commands that *write* count as writing: a repo-wide formatter/autofixer rewrites every worker's files at once, and an emitting build or codegen step has workers racing over shared artifacts — both are the lead's alone, never run while a worker is live.
- **Fan-out is not free, and the brief says so.** Every worker pays a full cold start re-reading the repo, and its final message is the only thing that comes back. A sibling project was observed spawning four workers for four one-line edits: four cold starts for work one agent finishes in a single pass. That is the failure the brief argues against, at length, because it is the only lever there is.
- **`CLAUDETM_HIVE_MAX_PARALLEL` (default 10) is a safety ceiling, not a target** (`core/hive.py`). It bounds concurrent workers — one lead plus up to N — and nothing else. A typo in the env var never ends a run: anything unset, unparseable or `<= 0` falls back to the default.
- **One checkout, shared by everyone.** Workers work directly in this same tree. Never a git worktree, never a clone, never a per-agent copy — the work has to land in the tree the lead commits from. The exclusive file sets in each worker's brief are the only lock there is; a worker that needs a file it does not own STOPS and reports the collision rather than resolving it silently.
- **The lead alone runs git.** Workers read, edit and run narrow checks; they never `add`, `commit`, `branch`, `checkout`, `stash` or `push`. That is what makes the shared checkout safe — one writer to the index, so no `.git/index.lock` contention and no half-staged tree — and it keeps history a single authored series. The lead waits for every worker to return, verifies on disk (`git status`, read the changed files), runs the **full** project gate once, and only then commits.
- **A worker's report is not evidence.** The lead never saw its tool calls. A worker that narrated a change without writing it is a real failure mode, so the lead re-checks on disk and re-does or re-assigns that piece itself.
- **Backgrounded workers are forbidden** — every worker is dispatched with `run_in_background: false`. A worker still writing after the lead ends its turn leaves a dirty tree behind a finished session, which the loop correctly reads as *unfinished* and re-runs the whole task.
- **The repository is still the evidence, unchanged.** A fanned-out session is verified like any other: clean tree or the task is not checked off, and `MAX_TASK_FINISH_ATTEMPTS` governs the retry with the leftover diff described as its own work to finish.
- **Bounded like one session, spends like several.** `MAX_TURNS` (400) and `--budget` are per *query*, and the terminal `ResultMessage` aggregates the lead plus every subagent — turns and cost accrue at N agents' rate against a single session's cap. An overrun is not a new failure mode: `error_max_turns`, task not checked off, same retry.
- **Fix sessions never fan out.** CI-fix, review-fix and conflict sessions are push-only and stay single-agent.

What it deliberately does **not** do: batch several tasks into one session, parallelise *across* tasks or PR groups, or give any agent its own working copy. The sibling TypeScript port (`../ai-task-master`) built cross-group parallelism and then pinned `--concurrency` to 1 — with one shared checkout, parallelism across groups buys nothing once git is serialized. The only place it pays is *inside* one unit of work, on disjoint file sets, with all git left to one agent.

### CI must actually have run

`ci_state == "SUCCESS"` is not sufficient. GitHub reports SUCCESS the moment the only registered checks are skipped ones — which is exactly what a PR looks like in the seconds after it is opened, before its jobs appear. Accepting it there leaves `waiting_ci` permanently on CI that never started, and with `--auto-merge --admin` that merges a red PR. `handle_waiting_ci_stage` treats **SUCCESS with `checks_passed == 0`** as unconfirmed and keeps polling through the same grace window as the no-CI fast path (`NO_CI_MIN_POLLS` 2 / `NO_CI_MIN_ELAPSED` 30s). A genuinely all-skipped run — every job path-filtered out — still passes, one poll later. `checks_passed` counts `SUCCESS`/`NEUTRAL` only, so a pending check makes the rollup PENDING and never reaches this test.

### What `--auto-merge` actually gates on (there is no approval gate)

Every user- and machine-facing description of `auto_merge` used to say PRs merge "when CI passes **and approved**" — wrong twice: there is no approval requirement anywhere in the code, and the conditions that *do* apply went unstated (#146). claudetm auto-merges when:

- **CI is green** — confirmed to have actually run (see above), with tolerated failures discounted,
- **no review thread is unresolved** — `waiting_reviews` counts `unresolved_threads`, routes anything actionable to `addressing_reviews`, and only advances at zero.

An approving review is **never required and never waited for**; under `--admin` claudetm explicitly *overrides* a base-branch policy that demands one. If you want a human checkpoint, that is `--no-auto-merge` or `--pause-on-pr`, not an approval the loop is silently ignoring.

The one review state that changes anything is **`CHANGES_REQUESTED`**: a human actively pushed back, so `_handle_requested_changes` refuses to merge over it. `APPROVED`, `REVIEW_REQUIRED`, no decision, and an unreadable decision all behave as before.

**`--admin` deliberately does not override `CHANGES_REQUESTED`.** `--admin` is passed on essentially every run here just to get past branch protection, so honouring it would delete the gate entirely. This is not an undefeatable block of the kind "Blocking is a last resort" warns about: the condition lives on GitHub rather than in the working tree, so a human clears it by approving or dismissing the review and the next cycle proceeds on its own — unlike a local, deterministic block that `resume --force` could never clear.

**The review-stage check timeout blocks by default**, and only `--admin` force-advances it — the same posture as the CI stage, on the same `CI_POLL_TIMEOUT` timer. It previously warned and proceeded toward merge with checks still pending, which is the opposite policy on the same clock. A *tolerated* failing or pending check (CodeRabbit "Review rate limited") no longer causes that wait or that block.

### Blocking is a last resort (unattended runs)

claudetm exists to do a lot of work without supervision, so **every block is a defect unless a human is genuinely required**. A run that dies at 3am on a GitHub 5xx has failed at its one job. Three operations used to end a run on their *first* failure — detecting a PR, merging it, and checking out the base after a merge — all with causes that resolve themselves in seconds.

`_GitOps._retry_transient(state, key, reason, hint)` is the shared primitive: leave `workflow_stage` alone and return None, and the stage simply re-enters next cycle. `MAX_TRANSIENT_RETRIES` (5) with linear backoff to `TRANSIENT_RETRY_MAX_DELAY` (60s); budgets are per `key` and instance-level (a resume starts clean). Clear it with `_clear_transient(key)` on success so flakiness doesn't accumulate across a long run.

Used at: PR detection (`ci_stage`), `merge_pr` (`merge_stage`), post-merge checkout of the base. A permanent failure — branch protection refusing a solo-authored PR without `--admin` — still blocks, just after the retries and with the attempt count attached.

The other half of the rule is recovery over refusal: `_PRRecovery` opens a missing PR itself, a dirty tree gets a finish session, and `loop_verification._open_missing_fix_pr` does the same for the verification path (which had no recovery at all). Recovery only ever fires on the unambiguous case — real feature branch, clean tree, commits over the base; anything else reports rather than pushing something it cannot vouch for.

Blocks that are correct and stay: a PR closed without merging, a tree still dirty after the finish budget, sitting on the base branch, attempt budgets exhausted.

#### A dirty tree at `ready_to_merge` is recovered, not refused

`gh pr merge` checks branches out, so it dies on a raw git error when the tree is dirty — hence the guard. But refusing was *all* the stage did, and that block is undefeatable by the command meant to defeat it: the condition is purely local and deterministic, so `claudetm resume -f` clears the status, re-enters `ready_to_merge`, re-reads the same unchanged tree and blocks again having run **zero** sessions. A green PR sat overnight behind two files an `expo prebuild` had rewritten (`D mobile/app/expo-env.d.ts`, `M mobile/app/tsconfig.json`) — nobody's edit, and nothing an agent couldn't have judged in a minute.

The tree now goes to a bounded cleanup session (`core/stages/merge_cleanup.py`), the same shape `_PRRecovery` uses for a dirty tree with no PR. The agent is the only thing here that can tell the PR's own unfinished work (finish, commit, push) from tooling droppings (discard); the orchestrator keeps what must not be guessed:

- it never commits anything itself,
- a session that left **new commits** on the branch routes the PR back to `waiting_ci` (`ci_poll_start_time` cleared) rather than merging on CI that ran before those commits existed — and commits it left *unpushed* are pushed deterministically, since a clean-but-unpushed tree is invisible to every later probe and the merge would land the PR without them, then delete the branch carrying them,
- bounded by `MAX_MERGE_CLEANUP_ATTEMPTS` (2, `state.merge_cleanup_attempts`, reset on task advance).

Still blocks on sight when recovery cannot be right: leftovers on the **base branch** (nothing there belongs to the PR, and a session must not commit to base), a crashed cleanup session, a failed push, or a tree still dirty after the budget.

#### `resume --force` refunds the attempt budgets

Same defect, one level up: the per-PR counters are persisted, so a stage that blocked *because* its budget was spent blocked again the instant a forced resume re-entered it. `StateRecovery.apply_recovery` now zeroes `ci_fix_attempts`, `conflict_fix_attempts`, `branch_sync_attempts`, `pr_finish_attempts`, `merge_cleanup_attempts`, `fix_finish_attempts` and `task_finish_attempts`. The budgets exist to stop an *unattended* loop from spinning; `-f` means a human looked at the run and did something about it.

### Limits — what bounds an agent, and what doesn't

Sessions are bounded in **steps**, not wall-clock. A wall-clock cap punishes a session that is legitimately slow (big test suite, slow CI) exactly as hard as one that is looping.

| Limit | Default | Override | What it does |
|---|---|---|---|
| `MAX_TURNS` (`core/agent_query.py`) | 400 turns | `CLAUDETM_MAX_TURNS` (`0` disables) | Runaway backstop per session, passed to the SDK as `max_turns`. Healthy sessions run tens of turns. Overrunning yields `error_max_turns` → the task retries (see above), it is never checked off |
| `max_budget_usd` | unset | `--budget` | Per-session cost cap. Same graceful path on overrun |
| `STREAM_IDLE_TIMEOUT_SEC` | 1800s | `CLAUDETM_STREAM_IDLE_TIMEOUT_SEC` | Max gap *between* stream messages — catches a hung SDK, not a slow agent |
| `POST_COMPLETION_IDLE_TIMEOUT_SEC` | 120s | `CLAUDETM_POST_COMPLETION_IDLE_TIMEOUT_SEC` | Only armed after `end_turn`, where the sole remaining message is the `ResultMessage` the SDK sometimes loses (#30333). Times out as *success* |
| `TrackerConfig.stall_threshold_seconds` | 300s | — | Orchestrator liveness, evaluated only *between* cycles. Every stage that runs an agent session or waits on GitHub heartbeats around it, so this never measures how long an agent may work |
| `TrackerConfig.max_session_duration` | 4h | — | Backstop, checked only while a session is active — which `should_abort` effectively never is. Must never be tightened to "typical" durations; real sessions run over an hour |
| `TrackerConfig.max_same_task_attempts` | 3 | — | Loop detection per task index. Sits one above `MAX_TASK_FINISH_ATTEMPTS` so a legitimate retry can't trip it |
| `CI_POLL_TIMEOUT` | 7200s | — | CI wait, not agent work |

### Up-to-date-before-merge (--sync-before-merge, opt-in)
- **Off by default.** A PR that merges cleanly is merged, even if the base moved under it. Syncing every behind-but-clean PR costs an agent session plus a full CI round on the common case, to catch a semantic clash that is rare — not a trade worth making automatically
- Pass `claudetm start --sync-before-merge` when the base is volatile enough that the untested merge result is a real risk (`TaskOptions.sync_before_merge`, default False). Then `ready_to_merge` compares the PR head against the live base (`get_pr_behind_by`, GitHub's compare API; `mergeStateStatus == "BEHIND"` is also honored) and routes a behind branch to the same agent session conflicts use
- Bounded by `MAX_BRANCH_SYNC_ATTEMPTS` (3) via `state.branch_sync_attempts`. Unlike conflicts, an exhausted counter **merges as-is** rather than blocking — a base that moves faster than CI must not stall the pipeline forever
- A failed/unavailable comparison never blocks a merge (degrades to "not stale")

### Merge Conflict Resolution (--resolve-conflicts)
- When `ready_to_merge` (or `waiting_ci`) sees `mergeable == "CONFLICTING"`, the conflict is handed to an agent session instead of blocking the run (`core/stages/conflict_stage.py`, stage `resolving_conflicts`). This is the *only* condition that triggers the session by default
- The session **rebases** onto the base (`git rebase origin/<base>`), resolves every hunk keeping both sides' intent — once per conflicting commit, `git rebase --continue` between — re-runs tests, then `git push --force-with-lease`. Rebase keeps PR history a clean series on top of the base instead of accumulating merge commits; the cost is that review threads anchored to rewritten commits go stale
- The session passes `allow_rebase=True` into the work prompt, which drops the blanket "NEVER rebase" rule a plain CI-fix session carries (`prompts_working._build_push_only_execution`). Fix sessions still never rebase — they only add commits
- Push re-triggers CI, so the PR re-enters `waiting_ci` and follows the normal path to merge
- Bounded by `MAX_CONFLICT_FIX_ATTEMPTS` (3) per PR via `state.conflict_fix_attempts`; exhausted attempts block with "manual resolution required" as before
- Disable with `claudetm start --no-resolve-conflicts` (`TaskOptions.resolve_conflicts`, default True)
- Counter resets on task advance, like `ci_fix_attempts`

### PR Limit (--prs flag)
- `--prs N` limits the maximum number of pull requests that can be created
- Injected into planning prompt to guide task organization
- Claude plans work to fit within the PR limit by grouping tasks intelligently
- Examples:
  - `claudetm start "Add auth" --prs 1` → Everything in one PR
  - `claudetm start "Build dashboard" --prs 3` → Max 3 PRs
- Default: unlimited PRs
- Useful for keeping changes focused and manageable

### Coding Style Generation
- Before planning, generates `coding-style.md` if it doesn't exist
- Analyzes `CLAUDE.md` and convention files to extract:
  - Development workflow (TDD, test-first patterns)
  - Code style conventions (naming, formatting)
  - Project-specific requirements
- Concise guide (~600 words) injected into planning and work prompts
- Preserved across runs (not deleted on success) to save tokens
- Uses Opus for high-quality extraction

### Release Guide Generation
- Before planning (when `auto_merge=True`), generates `release.md` if it doesn't exist
- Uses all tools (including Bash) to probe deploy infrastructure:
  - Deploy pipeline (Vercel, Netlify, Fly, Docker, GitHub Actions deploy jobs)
  - Health/smoke endpoints (searches routes for `/health`, `/healthz`, etc.)
  - Database (Prisma, Rails, Alembic migrations — checks migration status commands)
  - Monitoring (Sentry, Bugsnag — checks for API tokens in env)
  - Environment variables (checks `.env*` files for production access, never outputs secrets)
  - Cloud CLIs (checks for `gcloud`, `aws`, `az`, `fly`, `vercel` availability)
- Maps **accessible surface** — what the AI CAN verify vs what it CAN'T
- If nothing is found to verify, saves a guide that says so (release phase becomes no-op)
- Preserved across runs (not deleted on success) to save tokens
- Uses Sonnet for speed
- Skipped entirely when `auto_merge=False`

### Release Phase (Post-Merge Verification)
- **Two levels of release checks:**
  1. **Project-level** (`release.md`) — generic deploy capabilities, generated once
  2. **Per-PR** (`**Release checks:**` in plan.md) — specific checks for each PR group
- Runs automatically after each PR merge when `auto_merge=True`
- The planner sees `release.md` and generates per-PR release checks in `plan.md`
- After merge, agent runs release verification using Sonnet:
  - Checks GitHub Deployments API for deploy status
  - Hits health endpoints if available
  - Checks migration status if DB framework detected
  - Queries error monitoring for new errors (if API token available)
- **Graceful degradation** — if nothing is checkable, skips immediately
- **Quick-fix PRs** — if verification fails, creates a small fix PR (max 5 attempts)
  - Fix PR goes through normal PR lifecycle (CI, reviews, merge)
  - Then re-runs release verification
  - After max 5 attempts, moves on (doesn't block the pipeline)
- **No release phase when `auto_merge=False`** — human manages merges, they handle release

### Planning Prompt
- Instructs Claude to add `.claude-task-master/` to .gitignore
- Use Read, Glob, Grep to explore codebase
- Create task list with checkboxes
- If `release.md` available, add per-PR `**Release checks:**` sections
- Define success criteria
- Includes coding style guide and release guide for task planning

## Testing

Test in `tmp/test-project-1/`:
```bash
cd tmp/test-project-1
uv run claudetm start "Implement TODO" --max-sessions 3 --prs 2 --no-auto-merge
```

## Code Style

- **Max 500 LOC per file** - split larger files following SRP/SOLID
- **Single Responsibility** - one reason to change per module

### CI + Comments Combined
- When CI fails, both CI logs AND PR comments are fetched together
- Prevents two-step fixes (CI first, then comments)
- Single work session addresses all feedback at once
- `PRContextManager.save_ci_failures()` automatically calls `save_pr_comments()`

### Webhook Events
The system emits the following webhook events that can be registered at `/webhooks`:

**Run Lifecycle**:
- `run.started` - Emitted when orchestrator starts execution
- `run.completed` - Emitted when orchestrator finishes (success, failure, or blocked state)

**Task Status**:
- `status.changed` - Emitted when task status transitions between states (pending → in_progress → completed)

**CI/CD**:
- `ci.passed` - Emitted when CI checks pass for a PR
- `ci.failed` - Emitted when CI checks fail for a PR

**Plan Updates**:
- `plan.updated` - Emitted when plan is updated via mailbox/API or plan updater

Each webhook event includes:
- `event_id`: Unique identifier for the event
- `event_type`: The event type (one of above)
- `timestamp`: When the event occurred
- `data`: Event-specific payload (varies by event type)

**Webhook Delivery & Retry**:
- Deliveries are signed with `X-Webhook-Signature-256` header (HMAC-SHA256 of timestamp + payload)
- Failed deliveries retry with exponential backoff: `retry_delay * 2^(attempt-1)`, max 3 attempts by default
- Each delivery attempt includes a unique `X-Webhook-Delivery-ID` for idempotency tracking
- Non-retryable errors (4xx except 429): fail immediately
- Retryable errors (5xx, timeout, 429): retry with backoff
- Max retry delay capped at 30 seconds per attempt (`MAX_RETRY_DELAY` in `webhooks/client_types.py`)

### API Endpoints (REST)
Server runs on port 8000 by default (`claudetm-server`):

**Task Management**:
- `POST /task/init` - Create a new task
- `GET /status` - Get orchestrator status

**Mailbox** (Dynamic Plan Updates):
- `POST /mailbox/send` - Send message to mailbox
- `GET /mailbox` - Check mailbox status
- `DELETE /mailbox` - Clear mailbox

**Control**:
- `POST /control/stop` - Stop orchestrator
- `POST /control/resume` - Resume paused or blocked task

**Webhooks**:
- `GET /webhooks` - List webhooks
- `POST /webhooks` - Register webhook
- `DELETE /webhooks/{id}` - Delete webhook

**Repo Setup** (AI Developer Workflow):
- `POST /repo/clone` - Clone a git repository to `~/workspace/claude-task-master/{project-name}`
- `POST /repo/setup` - Setup cloned repository (install dependencies, create venv, run setup scripts)
- `POST /repo/plan` - Plan-only mode: analyze codebase and generate task plan without executing

**File Operations**:
- `DELETE /coding-style` - Delete the coding-style.md file from the state directory

### MCP Tools
Available via IDE integration:

**Task Management**:
- `get_status` - Get task status
- `pause_task` - Pause current task
- `stop_task` - Stop current task
- `resume_task` - Resume paused or blocked task

**Mailbox** (Dynamic Plan Updates):
- `send_message` - Send message to mailbox
- `check_mailbox` - Check mailbox status
- `clear_mailbox` - Clear mailbox

**Repo Setup** (AI Developer Workflow):
- `clone_repo` - Clone a git repository to `~/workspace/claude-task-master/{project-name}`
- `setup_repo` - Setup cloned repository (install dependencies, create venv, run setup scripts)
- `plan_repo` - Plan-only mode: analyze codebase and generate task plan without executing

**File Operations**:
- `delete_coding_style` - Delete the coding-style.md file from the state directory

## Workflow Integration

### Complete Work Loop

```
┌─────────────────────────────────────────────────────────────────┐
│                         PLANNING                                 │
│  Generate coding-style.md → Generate release.md (if auto_merge) │
│  Read codebase → Create task list → Define success criteria     │
│  (Planner adds per-PR release checks using release.md)          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      WORKING (per task)                          │
│  Make changes → Run tests → Commit → Push → Create PR           │
│                              ↓                                   │
│                      Check Mailbox ←── Messages from REST/MCP   │
│                              ↓                                   │
│              (If messages: Update plan, continue work)          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                       PR LIFECYCLE                               │
│  Wait for CI → Fix failures + comments → Resolve conflicts →    │
│  Merge                                                           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│              RELEASE PHASE (auto_merge only)                     │
│  Check deploy status → Health checks → DB migrations            │
│  → Error monitoring → Smoke tests                                │
│  Pass: continue │ Fail: quick-fix PR (max 5 attempts)           │
│  Skip: nothing to check │ No release.md: skip entirely          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                       VERIFICATION                               │
│  Run tests → Check lint → Verify criteria → Done                │
└─────────────────────────────────────────────────────────────────┘
```

### Dynamic Plan Updates

The orchestrator supports mid-execution plan updates via:

1. **CLI Resume with Message**: `claudetm resume "Add rate limiting to API"`
2. **REST API**: `POST /mailbox/send` with message content
3. **MCP Tools**: `send_message` tool from IDE integration

Messages are processed after each task completes. Multiple messages are merged with priority ordering (urgent → low) before updating the plan.

## Important Notes

1. **Always check if tasks already complete** - planning phase might finish some tasks
2. **Real-time output** - stream Claude's thinking and tool use
3. **Log rotation** - auto-keep last 10 logs only
4. **Clean exit** - delete state files on success, keep logs
5. **OAuth credentials** - handle nested JSON structure properly
6. **Working directory** - passed to the SDK as `cwd=`, never `chdir`'d; a process-global chdir would race concurrent queries and concurrent subagents
7. **Mailbox check** - orchestrator checks mailbox after each task completion
8. **CI + Comments** - fetched together to handle in one step
9. **Message priority** - 0=low, 1=normal, 2=high, 3=urgent
10. **Plan preservation** - completed tasks preserved when plan updates occur
11. **Hooks disabled** - `.claude/settings.json` disables Claude Code hooks to prevent "Stream closed" errors (known bug in Claude Code v2.1.39)
12. **Release phase** - runs after each PR merge when `auto_merge=True`, skipped when disabled or nothing to verify
13. **Release guide** - `release.md` generated once by probing deploy infra, preserved across runs like `coding-style.md`
14. **Per-PR release checks** - planner adds `**Release checks:**` sections to plan.md, specific to each PR's changes
15. **Release fix limit** - max 5 quick-fix PRs per release failure, then moves on (never blocks pipeline)

## Branch protection & `--admin`

`main` on the `developerz-ai` repos requires **one approving review**, so `gh pr merge` on a solo-authored PR is refused with "the base branch policy prohibits the merge" even with every check green. Two consequences:

- **Running claudetm here:** pass `--admin` (`claudetm start … --admin`, `claudetm merge-pr N --admin`, `claudetm resume --admin`) or the run blocks on a finished, green PR it cannot land.
- **Merging by hand:** `gh pr merge <n> --squash --admin`.

`--admin` overrides the policy — it does not satisfy it. It never skips CI or merges a conflicted PR; failing checks still route to the fix loop and conflicts to the resolver. It force-advances a *timeout* rather than blocking, at both the CI stage and the review stage (which now block by default, one policy on one timer). The one thing it does **not** override is `CHANGES_REQUESTED` — see "What `--auto-merge` actually gates on" above.

Releases go direct-to-main under the same owner bypass — a "pull request required" banner is a nudge, not a rejection.

## CI standard

- CI runs on Blacksmith (`blacksmith-2vcpu-ubuntu-2404`; `publish-test` on 4vcpu — deliberate). Every workflow declares a `concurrency` group with cancel-in-progress, and every job sets `timeout-minutes`. Publish workflows (PyPI / TestPyPI / Docker tag) are hard `cancel-in-progress: false` — publishes are irreversible.

### The local gate is the CI gate

`ruff check .`, `ruff format --check .`, `mypy .`, `pytest` — the **whole tree**, all three tools on the same scope. Run exactly that before pushing; anything narrower is not the gate. Two drifts made a narrower gate look green and shipped a red release commit (v0.1.79):

- **`mypy .` used to be unrunnable locally.** A leftover `build/` tree (gitignored, absent in CI's clean checkout) made it die on `Duplicate module named "claude_task_master"` before checking anything, so the habit became `mypy src` — which skips `tests/` and `scripts/`. `[tool.mypy] exclude` now covers `build|dist|coverage_html|htmlcov|.venv|tmp`, a no-op in CI, so the same command works in both places.
- **ruff was scoped to `src/ tests/` in CI while mypy checked everything.** `scripts/` and the root helpers were type-checked but never linted. Both now run on `.`.

### Tolerated check failures

Some status checks fail for reasons no commit can fix. `github/check_tolerance.py` holds a whitelist of `ToleratedFailure(check, description, reason)` rules; a failure matching one is counted as *skipped*, and the rollup `ci_state` is recomputed as if it weren't there (SUCCESS, or PENDING if other checks are still running). Built in: **CodeRabbit / "Review rate limited"**. Any other CodeRabbit failure, and the same message from any other check, still fails CI.

Add an exception by appending a rule to `TOLERATED_FAILURES`, or without a release via `CLAUDETM_TOLERATED_CHECK_FAILURES="check=description;other=description"`. Discounted failures are always logged (`~ CodeRabbit: 'Review rate limited' ignored — …`), never silent.

## Note

Do not use git worktrees — work directly in this checkout. If a task is big enough to need subagents, run them as a team in this same checkout: split the work into disjoint pieces so no two agents touch the same files.
