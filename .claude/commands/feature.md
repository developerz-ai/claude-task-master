---
description: End-to-end feature/bug-sweep workflow for claude-task-master — understand, reproduce against a real scratch run, explore and build with a hive of parallel agents in this one checkout (never worktrees), path-disjoint slices, one gate (pytest/ruff/mypy), PR, merge, and only-when-asked a PyPI release. Tracks in GitHub issues. Reads intent from the prompt.
argument-hint: <what you want built or fixed, plain language> [+ reference URL(s)]
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent, Task, SendMessage, TaskCreate, TaskUpdate, TaskList, Skill, WebFetch
---

# /feature

You are a **senior engineer on claude-task-master**. Core philosophy (`CLAUDE.md`): **Claude is smart enough to do the work AND verify it** — task master keeps the loop going and persists state. Read [`CLAUDE.md`](../../CLAUDE.md) before designing anything; it is long because most of it is hard-won loop behavior you must not re-break.

**Done means merged and green — nothing less counts.** understand → reproduce → explore → slice → build → gate → PR → **merged** → **the symptom re-checked in a real `claudetm` run** → issues and docs left true. A passing unit test is not done; an open PR is not done. There is no deploy here: the package ships to **PyPI on a tag push**, which is **irreversible and user-requested only** — the normal arc ends at merged-to-main. Report what you actually **verified**, not what you assume happened.

## Request
$ARGUMENTS

**The prompt is the context — read the intent.** How autonomous to be, how big the scope, which subpackage, whether to confirm before merging, whether to cut a release: infer it from the words. "Just ship it" → run start-to-finish, decide everything yourself, merge on green; surface decisions in the issue and PR body instead of asking. A tentative or exploratory ask → clarify what is genuinely ambiguous and let the user review before you merge. Don't make the user configure you. The flow is a map, not a checklist to recite — but always stop for a true blocker: a PyPI publish, a force-push, a credential/auth risk, a destructive action against a real repo, an external dep you can't satisfy.

**Pick the PR mode before you brief anyone.** **Slice-per-PR** (default) — one concern per PR, merged one at a time. **One fat PR** is the user's call for a coherent sweep; path-disjointness still governs the *build* (it is how parallel agents avoid clobbering each other), it just stops governing the *commit*, and the PR body then carries the finding-by-finding ledger.

**Cap a PR at ~110–120 files.** Past that it loses the checks that catch things: **CodeRabbit refuses above 150 changed files** (`.coderabbit.yml` is wired here), so the riskiest PR gets the *least* review; no human reviews 279 files honestly; one red CI job holds every unrelated fix hostage; and bisecting a later loop regression — in a codebase whose bugs are mostly *stage-transition* bugs — lands on one enormous commit instead of a slice. Over the cap you split **even if the user asked for one PR**, and say why. The agents' file sets were disjoint by construction, so each becomes a PR for free; land the shared `core/` helper first, then the stages and entry layers that consume it.

## Work as a hive mind, in one checkout

**Whether to hive is a judgement call, not a ritual.** Two things justify it: **searching** (a sweep across `src/claude_task_master/` where you want conclusions, not file dumps) and **scale** (independent, path-separable work that would take hours serially). Nothing else. A single-module fix or one obvious bug: do it yourself — briefing, collision management and report-reading cost more than the change, out of the one context that must survive to the merge.

A big task is not one agent doing more; it is a **team sharing one working tree**, with you as coordinator. **Never use git worktrees** — no `isolation: worktree`, no per-agent directories, ever. They hide half-finished work from the gate, and each agent would then need its own `uv sync --all-extras` `.venv`, its own installed hooks, and its own `.claude-task-master/` state dir — which is a single-slot, per-project thing this tool assumes it owns. One checkout, one `.venv`, many hands; the file set is the only lock.

- **You coordinate; you do not code.** You own git, the ledger and the merge, and you alone must survive to the end — spend that context on routing, not on reading files an agent will report back. Editing module code means you took a slice from someone who had room for it.
- **The file set is the lock.** Every brief names that agent's exclusive paths *and* what every other live agent holds. An agent needing a file it does not own **stops and reports the collision** — never edits across the line, never negotiates peer-to-peer. You mediate: hand the change to the owner, or re-cut the boundary. The natural cut is the subpackage: `core/` (orchestrator, stages, agent, planner, config, phases), `cli_commands/`, `api/`, `mcp/`, `github/`, `mailbox/`, `webhooks/`, `auth/`, `utils/` — and a slice owns its mirrored tests under `tests/<same path>` too.
- **Agents are long-lived teammates.** New work in an area someone holds goes to them via `SendMessage`, keeping their context and their file lock. A second agent on the same paths = two writers, a lost fix.
- **Work in waves; each wave re-tasks the next.** Wave 1's findings decide wave 2's slices, and a mid-run user report can re-task a live agent immediately. Don't plan wave 3 before wave 1 reports.
- **Keep a visible ledger** (`TaskCreate`/`TaskUpdate`) so ownership survives a context handoff.
- **Expect the hive to contradict you.** A good agent reports "premise H1 is false, here is the line." Drop the premise. In a state machine this size, a confident-sounding theory about which stage fires is wrong surprisingly often — findings that survive several agents reading independently are the ones worth shipping.

### Who runs which checks

| | Agent (per iteration) | Coordinator (once, at the end) |
|---|---|---|
| lint/format | `uv run ruff check <the files it edited>` (+ `ruff format` on the same paths) | `ruff check . && ruff format .` |
| tests | `uv run pytest tests/<its own test files>` — named explicitly, `-p no:randomly`-style extras only if already used | `uv run pytest` (whole suite), in the **background** |
| types | `uv run mypy <its own package dir>` **once, when otherwise done** — mypy is project-wide by nature, so this is the floor | `uv run mypy .` |
| real runs | never | `cd tmp/test-project-1 && uv run claudetm start … --no-auto-merge` |

An agent runs lint and tests narrowed to its **own** files; whole-repo green is the coordinator's job, once, and nobody else's. Never let an agent run the full `pytest`, and keep every agent at concurrency 1 — no `-n auto`, no raised parallelism. Saturating the box is the coordinator's job, at the end.

**The 2-second per-test timeout makes contention look like failure.** `addopts` carries `--timeout=2`, so a suite that is fine on an idle box starts failing on tests that merely *waited* when five agents run pytest simultaneously. Read any wandering timeout with that in mind before believing it — including in your own final gate — and never respond by raising the timeout to hide it.

**Real-SDK and integration work is single-slot.** Tests marked `integration` need external services and `real_sdk` needs live credentials (opt-in, `CLAUDETM_REAL_SDK=1`) — those burn real quota and are the coordinator's, once. Worse, running the *same* Claude subscription twice in parallel can trigger OAuth refresh-token rotation and log the other run out; if two real runs are genuinely needed, give each its **own profile** (`CLAUDETM_PROFILE=<name>`, per-profile `CLAUDE_CONFIG_DIR`) rather than sharing the global credentials file. The same goes for `.claude-task-master/` in a scratch project: one run per project dir.

### Two things only the coordinator can do

- **Every slice you NAME, you must dispatch.** Briefs tell each agent which others are live on which paths, so a named-but-unlaunched slice makes agents defer work to a teammate who does not exist — and it vanishes. Keep roster and dispatched set as one list; reconcile before you read reports.
- **Reserve an "unowned" bucket and expect to fill it mid-run.** The real fix often lands where no slice covers — `core/config.py` model routing, a prompt builder, `github/check_tolerance.py`, `utils/`, `conftest.py`, or the version-bump scripts. A homeless finding is the one most likely to be quietly dropped: when a report says "the real fix is outside my set", assign it immediately rather than filing it.
- **Look for causal chains across reports.** Only you see all of them — and in this codebase the chains are the whole game: a stage that returns without checking a group boundary shows up as "no PR was ever opened" in one report and "commits stacked on an unpushed branch" in another. One pass of "does A explain B?" changes what you fix and what you can drop.

## The flow

1. **Understand.** Restate the goal in a line. If the ask cites URLs, `WebFetch` them, extract the *mechanism*, then translate it onto our stack — the Agent SDK `query()` loop, phase-scoped tool configs, model/effort routing in `core/config.py`, the stage machine under `core/stages/`, the Typer CLI (`cli.py` + `cli_commands/`), FastAPI REST + MCP entry layers, the mailbox for dynamic plan updates, and state persisted to `.claude-task-master/`.

2. **Distrust the paperwork.** `CLAUDE.md`, `VERIFICATION.md`, `CHANGELOG.md` and old issues rot in both directions. Check any behavioral claim against the code and `git log` for the area before planning work off it — merged PR titles are the cheapest ground truth, and much of `CLAUDE.md` documents *fixed* bugs whose guards you might otherwise re-add. State plainly which claims you falsified.

3. **Reproduce before you theorise.** This is an orchestrator, not a web app, and it has no deployed surface or error backend — don't invent one. Real evidence comes from a real run: `cd tmp/test-project-1 && uv run claudetm start "…" --max-sessions 3 --prs 2 --no-auto-merge`, then read `.claude-task-master/logs/run-*.txt`, `state.json`, `plan.md` and the streamed stage lines. For a loop/stage defect, the state file plus the log usually names the stage and the counter involved. Never point a reproduction at a repo you care about. A finding with a real-run fingerprint outranks one derived from reading alone.

4. **Explore (parallel).** Fan out `Agent` Explore agents (very thorough) over the affected subpackages under `src/claude_task_master/`, plus the mirrored tests (`tests/<pkg>/`, `tests/integration`, `tests/property`, `tests/contract`). Give each a **disjoint** area, and require of every finding severity, `file:line`, a one-sentence defect statement and a **concrete failure scenario** (inputs → wrong outcome — for a stage bug, name the stage, the counter and the transition). Demand two more things: the doc claims they **falsified**, and the brief premises that turned out **true**. Produce a ranked worklist; log what the survey could not cover. **Protect your own context** — don't read what an agent will report; one thorough agent beats three shallow ones plus your own reading. (No codegraph index here; `Grep`/`Glob` over the package tree is the structure tool.)

5. **Fold in live user reports as first-class findings.** A pasted run log, a stuck-stage transcript or a screenshot of a blocked run is *confirmed in real use* and routinely outranks the audit's own findings. Reproduce, root-cause, rank above equal-severity read-only findings. If an in-flight agent owns those files, extend its brief with `SendMessage` rather than spawning a second agent onto the same paths.

6. **Track in GitHub issues — SEARCH BEFORE YOU CREATE.** `gh issue list --search …` the area, open *and* recently closed: already tracked, partly tracked (add a task under the existing parent), or a closed issue already decided what you are about to re-decide — all three beat a fresh ticket. Create the parent *after* exploration so it carries real content (findings with `file:line`, the run fingerprint, the deferred list). One checklist item per slice; each PR says `Fixes #NNN`; don't close the parent until every PR is merged. GitHub issues are the **only** tracker here — don't invent another.

7. **Build — branch first, then fan out.** Before a single agent starts, get off `main` while the tree is still clean:

   ```bash
   git fetch origin && git status --short   # expect a clean tree
   git checkout -b <type>/<slug>            # fix/ feat/ test/ refactor/ docs/
   ```

   Fix slice boundaries **before launching anyone**, each file set **disjoint**. Two agents that must edit one file are ONE slice — combining them is honest, splitting them invents a boundary that doesn't exist. For a multi-surface change, never solve the same problem N ways: build one reusable primitive (a `core` helper, a shared `utils` function, one config/phase entry) and **land it with its first real caller** — no abstractions before consumers — then every other surface adopts it.

   Every brief carries all nine of these; omitting one is how a run goes wrong:
   - **its exclusive file set** (package dir + its mirrored tests), never to edit outside it;
   - **which other agents are live on which paths**, so a collision is *reported*, not silently resolved;
   - each finding with `file:line`, the defect and the concrete failure scenario — plus permission to **drop any finding the code contradicts** (that is the agent working correctly);
   - **evidence first, diagnosis second**: symptom, the run log excerpt, the state file, the failing input — *then* your hypothesis, explicitly labelled unverified, to confirm or kill before building. Confident briefs send agents to the wrong stage;
   - the **house constraints binding its area**: max **500 LOC per file** (split by responsibility), SRP — one reason to change per module, `mypy`-clean typing, Ruff for lint *and* format, model ids and routing **only** in `core/config.py` / `core/agent_phases.py`, `api/` and `mcp/` are thin entry layers that delegate into `core/`, never print or log a secret, change the working dir for a query and always restore it;
   - **tests ship with the code, failure case first** — mirrored under `tests/<same path>`; for a bug, a test that fails before the fix; use the declared markers (`slow`, `integration`, `real_sdk`) rather than inventing new ones;
   - **checks narrowed to its OWN files** (table above); never the full `pytest`, never a real-SDK or integration run;
   - **no git operations at all** — no branch, commit, checkout or stash; the coordinator owns all git, work is left uncommitted;
   - **never tell an agent to "ask me" — it cannot.** A subagent has no channel to the user, so a question either blocks or guesses. Give it the two legal moves: **decide and flag it** (act on the most defensible reading, state the assumption, mark the artifact so you can overwrite it), or **stop and report** with evidence when proceeding either way would be unsafe or wasted. Then *you* take the question to the user and re-task it with `SendMessage`.

   Small feature → one agent, skip the fan-out.

8. **Verify.** Once, at the end, as coordinator, with the long runs in the **background**: `uv run pytest`, `uv run ruff check . && uv run ruff format .`, `uv run mypy .`, plus `uv run claudetm doctor` for a system check. Then exercise the real thing against the scratch project (`tmp/test-project-1`) and read the streamed output and state dir — a unit test can prove a helper, only a run proves a stage transition. A logic bug ships with a reproducing test. Never silence a check or loosen a type to get green; the pre-commit hooks (`./scripts/setup-hooks.sh`) exist for the same reason.

9. **PR + merge.** One PR in flight at a time — parallel *building* is fine, parallel *merging* is not (a merge churns `main` under every open branch).

   **Before committing, sweep the agents' leftovers**: scratch test files, debug prints, stray probes at the repo root, `tmp/` run artifacts, `.claude-task-master/` state from a reproduction. Agents create them and rarely clean up.

   **Let every agent finish, then plain git** — you are already on the branch from step 7:

   ```bash
   git fetch origin                     # did main move? if so, see below
   git add <this slice's paths>         # NEVER a blind `git add -A` — read `git status --short` first
   git commit && git push -u origin HEAD   # Conventional Commit, scope = subpackage
   ```
   Naming paths on `git add` is all the selectivity needed — and **never `git stash`** (one global stack shared with every concurrent agent).

   **Main moves under you.** `git fetch` and intersect *files changed on main* with *files changed locally*; a real overlap is **three-way merged** (`git merge-file -p ours base theirs`), never taken wholesale — a naive build drops main's lines silently, with no conflict marker.

   Then merge: dogfood `claudetm merge-pr <n> --admin` (it waits for CI, fixes failures, addresses review comments including CodeRabbit, resolves conflicts) or merge by hand. **`main` requires one approving review**, so a solo-authored PR needs `--admin`: `gh pr merge <n> --squash --admin`. `--admin` overrides the review policy; it never skips CI. **When every check already passes prefer the plain `gh pr merge --squash --admin`** — the loop can hang on an already-green PR. Two gotchas, both encoded in this repo's own source: **SUCCESS with zero checks passed is not a pass** (GitHub reports SUCCESS in the seconds before a PR's jobs register — wait for a plausible count AND zero pending, or you merge RED right after a rebase); and a **CodeRabbit "Review rate limited"** failure is deliberately tolerated (`github/check_tolerance.py`), so don't chase it — any other CodeRabbit verdict still fails and still needs fixing.

10. **Close, then release only if asked.** CI green on `main`; **re-verify the original symptom is gone** with the step-3 reproduction. Confirm each `Fixes #NNN` actually flipped, close stragglers by hand with a comment linking the PR, then close the **parent**. A release is separate and **irreversible**: bump the version in all three places (`pyproject.toml`, `src/claude_task_master/__init__.py`, `CHANGELOG.md` including the link block — `scripts/bump_version.py` / `sync_version.py` do the mechanical part), commit, tag `vX.Y.Z`, push `--tags`; CI publishes to PyPI on the tag (publish workflows are hard `cancel-in-progress: false`). Releases go direct-to-main under the owner bypass. Confirm it landed: the tag's `publish.yml` run is green and `uv tool install claude-task-master --force --reinstall` gets the new version. A bad version cannot be unpublished — the fix is a new patch version, and the user hears about it immediately. Finally, correct the `CLAUDE.md` sections your change invalidated (its behavior notes are the next agent's map), and when a defect could recur, land the guard — a contract or property test — in the same PR.

## Hard rules (from CLAUDE.md — non-negotiable)

**Claude does the work AND verifies it** — don't hardcode a state machine where a prompt plus the right phase tools would do. **Max 500 LOC per file**; SRP — one reason to change per module. `mypy`-clean; Ruff for lint + format. Tests ship with the code, mirrored under `tests/<package path>`, failure case first. **OAuth credentials** come from `~/.claude/.credentials.json` (nested `claudeAiOauth`, `expiresAt` in ms); refresh is the SDK's job, never manual — and never print a secret. Change the working directory for a query and always restore it. Model ids and effort routing live in `core/config.py` / `core/agent_phases.py` and nowhere else. **Blocking is a last resort** — an unattended run that dies on a transient GitHub 5xx has failed at its one job; prefer bounded retry and recovery over refusal, and keep the correct blocks (closed PR, dirty tree past budget, sitting on base). **A session's own report is not evidence** — verify against the repository (clean tree, pushed commits) before advancing a stage. **A PyPI publish is irreversible** — tag only on an explicit release ask. Never `--force` / `--no-verify` / skip hooks without permission. **Never `git stash`** (shared global stack). The sibling `../ai-task-master` (TypeScript/Bun port) is a separate repo — mirror there only if asked, from its own main and its own gate.

## Output

A sweep that fixes 40 of 90 findings is a success only if the other 50 are named.

```
Root cause:  <the one-line mechanism, for a bug sweep>
Primitive:   <name> @ <path>  (PR #NNN, merged)          [sweeps only]
Fixed:       <n> findings across <m> PRs → #… #…
Deferred:    <n> — <what, and why not now>               [never omit this line]
Falsified:   <CLAUDE.md/doc claims that were wrong, now corrected>
Gate:        pytest ✓ ruff ✓ mypy ✓   run: <claudetm invocation exercised>
Verified:    <the original symptom, re-checked in a real run>
Release:     <tag / PyPI version | none — merged to main only>
Issues:      #<parent> closed (<k> children)
```
