---
description: Write a concise, self-contained execution plan to docs/plans/<YYYY>/<MM>/<DD>/<1NN>-<slug>/ for another AI to implement
argument-hint: [what you want done]
allowed-tools: Write, Read, Glob, Grep, Task, Bash
---

# /planx

Produce a concise plan another AI can execute with zero extra context. Plan only — no implementation, no code execution, no edits outside the plan dir.

## Goal
$ARGUMENTS

## Steps

1. **Resolve path.** Run `date +%Y`, `date +%m`, `date +%d`. Dir = `docs/plans/<YYYY>/<MM>/<DD>/`. `Glob docs/plans/<YYYY>/<MM>/<DD>/1*` → next number = highest existing `1NN-*` + 1, else `101`. Slug = kebab-case title, max 5 words. Final plan dir: `docs/plans/<YYYY>/<MM>/<DD>/<1NN>-<slug>/`.

2. **Explore.** `Task` (subagent_type=Explore, thoroughness="very thorough"): existing patterns + files to touch (`file:line`), the right subpackage under `src/claude_task_master/*` (`core` orchestration/agent/config, `cli_commands`, `api`, `mcp`, `github`, `mailbox`, `webhooks`, `auth`, `utils`), the matching tests under `tests/*` (which mirror the package tree; note unit vs `tests/integration` vs `tests/property`), the phase/tool contracts (`core/agent_phases.py`, `core/config.py` `ModelConfig`), state-dir shape (`.claude-task-master/`), and gotchas. Skip only for trivial asks.

3. **Write the plan as multiple files** in the plan dir — never one big `plan.md`. Always produce an `overview.md` index plus one `<NN>-<aspect>.md` per separable area (e.g. `01-config.md`, `02-orchestrator.md`, `03-cli-command.md`, `04-api-endpoint.md`, `05-mcp-tool.md`, `06-tests.md`). Split by area of work so each file is independently executable and stays short. Match the terse house style — fragments, `file:line` refs, tables.

   **`overview.md`** — the map. Sections:

```markdown
# <Title>

## Goal
1-2 sentences: what + why.

## Context
- Stack facts the executor needs (Python 3, `uv`, Claude Agent SDK `query()`, Typer CLI, FastAPI REST + MCP server, OAuth from `~/.claude/.credentials.json`, state persisted to `.claude-task-master/` — only what's relevant).
- Reference patterns: `src/claude_task_master/<pkg>/<thing>.py:12` — follow this for Z.

## Plan files (execute in order)
1. [`01-<aspect>.md`](01-<aspect>.md) — one line: what it covers.
2. [`02-<aspect>.md`](02-<aspect>.md) — ...

## Done when
- Verifiable acceptance criteria spanning the whole feature.

## Risks / open questions
- Anything the executor must decide or watch.
```

   **Each `<NN>-<aspect>.md`** — one slice of work. Sections:

```markdown
# <NN> — <Aspect>

> Part of [`overview.md`](overview.md). Depends on: <NN-prior or "none">.

## Files to change
- `path:line` — what changes, why.

## Steps
1. Ordered, concrete actions. Reference `Class.method` / `file:line`, don't restate.

## Tests
- What to add/run. Tests written with the code, mirroring the package path under `tests/`. Commands: `pytest`, `ruff check . && ruff format .`, `mypy .` (or `uv run <cmd>` in dev mode).

## Done when
- Verifiable acceptance criteria for this slice.
```

4. **Write a `status.yml`** in the plan dir (alongside `overview.md`) — the live tracker for this plan. New plans start `not_started` / `0%`. Get `created_by` + `owner` from `git config user.name` (the person running /planx). Leave `worked_by` empty — the executor sets it to their own `git config user.name` when they pick the plan up, so a plan written by one person can be worked by another. Shape:

```yaml
plan: <1NN>-<slug>
title: <human title from overview.md>
status: not_started        # not_started | in_progress | blocked | complete | superseded
created_by: <git config user.name>   # who authored the plan
worked_by: ""              # who is executing it; empty = unclaimed; executor fills with their git user.name
owner: <git config user.name>
percent: 0                 # 0–100, overall completion
current_focus: ""          # where it's at right now / next slice to pick up
slices:                    # one row per <NN>-<aspect>.md slice
  - file: 01-<aspect>.md
    status: not_started      # not_started | in_progress | complete
    percent: 0
evidence: []               # commits/PRs proving progress, e.g. ["#324", "abc1234"]
notes: ""
last_updated: <YYYY-MM-DD>
```

   Keep `status.yml` machine-readable (valid YAML, the enums above). It's the one file in the plan dir that IS a tracker — the `.md` slices stay reference maps (no checkboxes there).

## Rules
- Compact English. Fragments over sentences. `file:line` and `Class.method` symbol refs over prose. Tables for structured data.
- Reference-only: point at code, don't paste it or re-explain it ("follow `x.py` but ...").
- No checkboxes (`[ ]`). Plain bullets. The plan is a reference map, not a tracker.
- Multiple files always: `overview.md` + `<NN>-<aspect>.md` slices. Never a single `plan.md`.
- Self-contained: executor reads only `overview.md`, the slice it's on, and the files those cite.
- Respect `CLAUDE.md`: **Claude is smart enough to do work AND verify it** — task master just keeps the loop going and persists state. No hardcoded state machines where a prompt + the right phase tools would do. Thin orchestrator; default to deletion; no abstractions before consumers.
- Stack rules: Python, typed (`mypy .` clean, avoid bare `# type: ignore` without a why-comment). Ruff for lint + format (line-length 100), no other formatter. **Max 500 LOC per file** — split larger files following SRP/SOLID (one reason to change per module). Package layout is `src/claude_task_master/<pkg>/`; tests mirror it under `tests/<pkg>/`. Model/effort routing lives in `core/config.py` (`ModelConfig`) and `core/agent_phases.py` — don't hardcode model ids elsewhere.
- Anything touching auth/credentials, the release/publish path (PyPI on tag push), or CI (`.github/workflows/`) → its own `<NN>-<aspect>.md`, and call out the irreversible bits (a publish can't be undone).
- The sibling repo `../ai-task-master` is a feature-parallel TypeScript/Bun port — if a change needs to land there too, note it as a separate `<NN>-<aspect>.md` (edited from its own repo, not here).

## Output
```
✓ docs/plans/<YYYY>/<MM>/<DD>/<1NN>-<slug>/overview.md
  + 01-<aspect>.md, 02-<aspect>.md, … (one per area)
  + status.yml (tracker — status/owner/percent/current_focus)
Next: run an executor on overview.md.
```
