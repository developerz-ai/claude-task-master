# CLAUDE.md

## Worker non-negotiables

- Do the assigned task only. Declare your write set; stop and report work outside it.
- Work in this checkout. Never create a worktree, clone, per-agent copy or shared git stash.
- Preserve unfinished work and persisted state. Resume the existing diff; do not reset or discard it.
- Read the affected code, reproduce bugs with a failing test, then fix the cause and ship the guard.
- Verify against repository state and actual check output, never an agent's completion report.
- Workers run only their assigned scoped checks. The lead runs the full gate once after all return.
- Never run a repo-wide formatter, autofixer, build or codegen while workers are editing.
- Only the lead handles git; when an external harness owns git, leave all git operations to it.
- Never print, log, commit or copy credentials. Authentication and refresh stay at the SDK boundary.
- Do not bypass CI, review gates, hooks or branch protections. Missing checks are not green checks.
- Publishing is irreversible: release/tag/publish only on an explicit release request.
- Disclose bot identity in comments. Report what was checked, what failed and what remains unverified.

## Purpose and stack

**Core philosophy: Claude is smart enough to do work AND verify it.** Task master keeps the loop
running and persists state until the goal is achieved or human input is genuinely required.
Prefer bounded recovery over a deterministic block; do not replace agent judgement with an
unnecessary hardcoded workflow. Keep safety and completion checks machine-enforced.

| Area | Authority / convention |
|---|---|
| Package | `claude-task-master`; source layout under `src/claude_task_master/` |
| Python | Package minimum **3.12** (`pyproject.toml`); development setup uses **3.14** (`bin/setup`) |
| Agent | Claude Agent SDK `query()` and `ClaudeAgentOptions`; Claude Code subprocess |
| CLI / models | Typer, Pydantic 2, Rich; model IDs/config in `core/config.py`, phase routing in `core/agent_phases.py` |
| Networking | httpx; MCP 2 in base dependencies; optional REST extra uses FastAPI/Uvicorn and bcrypt |
| Tooling | uv, Ruff, mypy, pytest, pytest-asyncio/timeout/xdist/cov, Hypothesis |
| Services | Docker Compose; Debian/Ubuntu setup expects mise, Docker Compose and dpkg |

Paths beginning `core/` below are relative to `src/claude_task_master/`.
Use `pyproject.toml` as dependency/tool configuration authority rather than duplicating version pins.

## Commands and verification

| Command | Purpose / effects |
|---|---|
| `./bin/setup` | **Writes:** installs host prerequisites if missing, mise tools, uv 0.13 and Python 3.14; syncs all extras; creates an empty external `claudetm-profiles` volume. Does not copy credentials or start services. |
| `./bin/dev` | **Starts/builds services:** `docker compose up --build --wait --wait-timeout 180`; waits for REST health readiness, not a build deadline. |
| `./bin/stop` | Stops Compose services without deleting their data. |
| `./bin/check` | **Full gate:** whole-tree Ruff lint and format check, mypy, pytest with two workers/coverage, isolated temporary package build, CLI smoke probes. Writes coverage/build artifacts; lead/harness only. |
| `uv run ruff check .` | Non-autofixing lint check; `--fix` is a writing operation. |
| `uv run ruff format --check .` | Non-writing format validation. `uv run ruff format .` rewrites files; never substitute it for a check. |
| `uv run mypy .` | Whole-tree type check, including tests/scripts; narrowing to `src` is not the full gate. |
| `uv run pytest tests/<area>` | Scoped tests when assigned; use the repository markers and fixtures. |
| `python verify_docs_links.py` | Read-only repository Markdown path/anchor check; separate from `bin/check`. |
| `uv sync --all-extras` | **Writes:** development dependency installation, not verification. |
| `./scripts/setup-hooks.sh` | **Writes:** installs the development pre-commit hook; the installed hook runs the gate (`bin/check`) and propagates its exit status. |
| `uv run claudetm --help` | CLI smoke check; `doctor` and `status` may fail without credentials/state and are tolerated probes in `bin/check`. |

### Where the gate's tools come from

CI installs the project with `uv pip install -e ".[all]"`, and that install path does not read
`uv.lock`: CI runs the newest release inside pyproject's dev-extra ranges — `ruff>=0.16.1,<0.17`
and `mypy>=2.4.1,<2.5`. Local `uv sync --all-extras` and `uv run` do read `uv.lock`, so they run
the locked ruff 0.16.1 and mypy 2.4.1. A green local `bin/check` is therefore evidence for the
locked versions only; it is not proof that CI is green.

`requirements.txt` is a committed `uv pip compile` output of `pyproject.toml`, so it floats to the newest in-range releases (fastapi 0.149.0 against the lock's 0.139.2, pydantic 2.14.1 against 2.13.4); only claude-agent-sdk, ruff and mypy are held at `uv.lock`'s resolution, and it is not a gate input.

Follow the applicable skill before verification: `.claude/skills/verify-change/SKILL.md`,
`.claude/skills/docs-links/SKILL.md` or `.claude/skills/local-install/SKILL.md`.
Run the narrow reproducer first and the full gate once at the end; never weaken a test/type/lint guard
to obtain green. Ruff deliberately excludes Markdown. Separate check commands from writing commands.
Real-SDK tests are opt-in (`CLAUDETM_REAL_SDK=1`), require credentials and spend quota.
Use a disposable scratch project such as `tmp/test-project-1/` for authorized real runs, with
`--no-auto-merge`; never reproduce against a valuable repository or share a live run's state directory.

## Source and test structure

| Path | Responsibility / test location |
|---|---|
| `src/claude_task_master/core/` | Agent queries, phases/prompts, config, planning, state, loop and `stages/`; mirrored by `tests/core/` |
| `src/claude_task_master/cli.py`, `cli_commands/` | Typer entry point and command handlers; `tests/cli_commands/` |
| `src/claude_task_master/wrapper.py`, `bin/claudetm` | Main console wrapper/config loading; `tests/test_wrapper.py`, `tests/test_bin_scripts.py` |
| `src/claude_task_master/api/`, `mcp/` | Thin REST/MCP entry layers delegating into core; corresponding `tests/api/`, `tests/mcp/` |
| `src/claude_task_master/server.py`, `server_runners.py` | Unified server runners; `tests/test_server.py` |
| `src/claude_task_master/github/` | PR/CI/review operations and check tolerance; `tests/github/` |
| `src/claude_task_master/mailbox/`, `webhooks/`, `auth/`, `utils/` | Communication, delivery, auth and utilities; mirrored test packages |
| `tests/integration/`, `tests/property/`, `tests/contract/` | Cross-component, Hypothesis and contract guards; shared fixtures in `tests/conftest.py` |
| `docs/README.md`, `README.md`, `examples/` | User documentation, navigation and examples; use existing pointers, not a second project brain |
| `.claude/agents/`, `.claude/skills/` | Project specialists and repeatable verification procedures |

Console scripts are declared in `pyproject.toml`: `claudetm` loads the wrapper, `claudetm-py` bypasses
it, and `claudetm-mcp`, `claudetm-api`, `claudetm-server` start their respective interfaces.

## Coding conventions

| Rule | Apply it |
|---|---|
| Size and design | **Max 500 LOC per file**; SRP/SOLID, one reason to change per module. Split by responsibility. |
| Typing | Typed Python; complete function annotations and explicit optional types; keep mypy clean. |
| Formatting | Ruff, 100-column target, double quotes, spaces; import ordering enforced by Ruff. |
| Tests | Ship tests with code under mirrored package paths; failure case first for bugs. |
| Markers | Use declared `slow`, `integration`, `real_sdk`, `property`; do not invent markers. |
| Entry layers | Keep API/MCP thin; reuse core logic instead of duplicating orchestration. |
| Configuration | Keep model IDs/effort routing centralized; use existing config/profile/env surfaces. |
| Output | Stream through `core/console.py`; no emoji in the printer, no secrets anywhere. |
| Scope | Smallest correct change; unrelated defects are separate work, not opportunistic refactors. |

## Completion, state and recovery

The orchestrator's application contract below does not grant a worker permission to operate git
when a lead or harness owns it. Repository evidence, not prose, determines stage advancement.

| Situation | Required invariant / source pointer |
|---|---|
| Grouped task | Non-final tasks owe **commit only**, not early push/PR. Last-in-group and `--pr-per-task` owe commit, push and PR URL (`core/task_runner_session.py`). |
| Group boundary | Groups are contiguous; repeated PR headings create separate instances. A skipped `[x]` task still closes its group off the base branch (`core/task_group.py`, `core/loop_working_stage.py`). |
| Cursor | `current_task_index` is a saved cursor, not a monotonic counter. Preserve deliberate rewinds and reconcile it after plan updates. Hive completes one task, not one per worker. |
| Cut-off work | Terminal SDK errors yield `ran_incomplete`; a definite dirty tree also means unfinished. Resume the leftover diff, not a clean restart. `MAX_TASK_FINISH_ATTEMPTS` is 2, then PR recovery takes over; overall session limits still apply. |
| Push-only fix | CI/review/conflict fixes must commit **and push**. Detect dirty trees and unpushed commits before resolving threads or advancing. Retry up to `MAX_FIX_FINISH_ATTEMPTS` (2), then block; undelivered CI fixes refund `ci_fix_attempts`. |
| Planning | Never persist a cut-off plan. `PlanUpdater` validates real tasks, preserves completed tasks and backs up before overwrite. Mailbox and `resume "message"` update pending work, not completed work. |
| Missing PR | `core/stages/pr_recovery.py`: clean/ahead pushes and opens; clean/not-ahead closes the group; dirty gets at most two finish sessions. Base branch, failed comparisons/push/create, crash or exhausted budget block. |
| Dirty merge | `core/stages/merge_cleanup.py`: at most two cleanup sessions, never auto-commit leftovers. New commits must be pushed and return to `waiting_ci`; never merge using CI for an older head. Base-branch leftovers block. |
| Git probe | Preserve three states: clean, dirty, unreadable. Push/PR-opening fails closed on unreadable; fix/merge guards act on definite dirty state, not failed probes. |
| Transient failures | Use bounded `_GitOps._retry_transient`, clear its key on success; do not turn transient PR detection/merge/checkout failures into immediate human blocks. |
| Budgets | Keep recovery bounded and counters reset on task advance. Explicit forced resume refunds persisted attempt budgets (`StateRecovery`); do not implement endless retry. |
| Merge checks | CI must actually have run; SUCCESS with zero passed checks is unconfirmed during the grace window. Respect actionable review threads and human requested changes. A worker never overrides a gate. |
| Conflicts/sync | Conflict resolution may rebase only via its explicit `allow_rebase` path; ordinary fix sessions add commits. `--sync-before-merge` is opt-in, not an unconditional base-sync session. |

State lives in `.claude-task-master/`: goal/criteria, checkbox `plan.md`, `state.json`, progress,
context, mailbox, generated coding-style/release guides, logs and PR debugging evidence.
Mailbox messages are checked after tasks, merged urgent-to-low, then passed to `PlanUpdater`.
Exit **0** cleans successful-run state but preserves `logs/`, `coding-style.md`, `release.md` and the
last ten logs; **1** (blocked) and **2** (interrupted) preserve state for resume. Do not clean a live run.

## Agent, credentials and prompt invariants

| Area | Rule / pointer |
|---|---|
| Working directory | Pass `cwd=str(self.working_dir)` in SDK options, validate existence, **never process-global `chdir`**; concurrent queries share the process (`core/agent_query_execute.py`). |
| Phase tools | Planning defaults to Read/Glob/Grep/WebFetch/WebSearch; verification to Read/Glob/Grep/Bash; working to all tools. `allowed_tools` is auto-approval, **not a sandbox**, under `bypassPermissions`; restriction requires actual tool denial. |
| Terminal result | After `ResultMessage`, retain accumulated output and error status despite trailing stream error/stall. Pre-terminal failures still enter retry logic; do not swallow them as success. |
| Error classification | Prefer structured SDK status/payload over prose; token-boundary text fallback. Keep `core/agent_error_classify.py` importable without the SDK. Unknown query failures use the bounded failure budget. |
| Usage limits | All query phases use `run_query_riding_out_usage_limits` (`core/usage_limit.py`): bounded, interruptible waits. A leaked refusal consumes no task-finish attempt, never checks a task off and is not distilled into context. |
| Context | Prompt builders use `load_context_for_prompt()` (32k tail cap); raw `load_context()` is for append/distill/display. Extract learnings from output tail and bounded prior context, without restating the backlog. |
| Limits and cost | Bound sessions by turns/budget, not typical wall-clock duration. Preserve idle/stall distinctions. Terminal cost/usage aggregates lead and workers; record all query phases. |
| OAuth | Nested `claudeAiOauth` in the active credentials file; `expiresAt` is milliseconds. SDK/binary refreshes tokens, never custom manual refresh. Re-authentication is an operator action. |
| Profiles | OAuth uses isolated `CLAUDE_CONFIG_DIR`; API-key profiles inject env at the SDK subprocess boundary and skip OAuth-file checks. Do not expose either credential form. |
| Isolation | Use distinct profiles for concurrent accounts/runs; sharing one subscription can rotate refresh tokens. Ambient `default` clears the active pointer unless shadowed by an existing registry entry. |
| Models | Defaults/fallbacks belong in config/phase modules. `context_windows` is currently inert, not a grant of larger context; do not append CLI-only `[1m]` aliases to portable API model IDs. |

## Hive ownership and dispatch

Parallelism is **inside one task**, never across tasks/PR groups; it defaults on but is optional.
Use few large independent pieces: two or more workers or none, never one worker for a micro-edit.

- Gate prompt and registration with `fan_out_enabled(parallel, push_only)` in `core/hive.py`;
  push-only fixes, resumed dirty tasks and `[quick]` tasks do not fan out.
- When `agents_for()` returns None, deny `DISPATCH_TOOLS` (`Task`, `Agent`); absent definitions alone
  do not stop built-in dispatch. A caller without a loader fails closed.
- Match project specialists first, generic `hive-worker` second. The CLI loads project definitions
  via `setting_sources: ["project"]`; `get_agents_for_working_dir` supplies built-ins only.
- Each brief names exclusive files, other owners, API/caller impacts, conventions and allowed checks.
  Cite paths rather than pasting source. If callers overlap, keep the shared work with one owner.
- Dispatch independent pieces together and work on retained pieces meanwhile. Size the team for
  both real seams and available machine resources; the ceiling is not a target.
- Use the same `hive_max_parallel()` (default 6) in the brief and CLI concurrency env.
- Preserve `hive-worker` definition guards: `background=False`, denied Task/Agent,
  `maxTurns=hive_worker_max_turns()` (default 200), effort from `hive_worker_effort()` (default high).
- Workers never spawn workers, touch others' paths or run git. One writer per shared artifact;
  lead/harness alone runs emitting tools and the full gate after workers finish.
- The lead verifies the actual diff and check output. Query turn/cost limits aggregate the team;
  fan-out does not change completion evidence or retry semantics.
- Keep `core/hive_roster.py` independent of console/SDK imports; `MessageProcessor` renders it.
  A successful dispatch result is an acknowledgement, not completion; only failed dispatches retire
  workers from that signal. Never invent rows from unrelated top-level tool errors.

See `core/prompts_working_hive.py`, `core/subagents.py` and the project hive specialist for details.

## Releasing and CI

Release only on an explicit request; a normal code change does not authorize a tag or publish.
Synchronize **all** version locations:

| Location | Required update |
|---|---|
| `pyproject.toml` | Project `version` |
| `src/claude_task_master/__init__.py` | `__version__` |
| `bin/claudetm` **and** `src/claude_task_master/bin/claudetm` | Both `SCRIPT_VERSION` copies; the packaged copy ships and prints the version first |
| `CHANGELOG.md` | Release entry and bottom link block |

Tag pushes trigger PyPI publication. Follow authorized release workflow and merge protections;
never use owner/admin bypass as a worker instruction. Verify published version/install only when
release work is authorized (`.claude/skills/local-install/SKILL.md`).
Post-merge runtime release checks use generated `release.md` plus per-PR plan checks when auto-merge
is enabled; skip unavailable surfaces, and route fixes through normal PR gates, not direct publish.

CI configuration lives in `.github/workflows/`: GitHub-hosted `ubuntu-latest` runners, concurrency
groups and job timeouts. Irreversible publish workflows keep `cancel-in-progress: false`.
Check tolerance is explicit and logged in `github/check_tolerance.py`; do not broaden exceptions to
hide failures. Existing tolerated quota notices are not permission to ignore unrelated failed checks.
