# Reviewer instructions — developerz-ai/claude-task-master

> Read by the developerz.ai reviewer at EVERY review of this repository, at the reviewed
> commit, as this repo's own layer of the reviewer's prompt — established by dz-runner setup mode.
> It refines the platform rules (a finding is cited or withheld; the bot always discloses)
> and never overrides them. Edit freely; keep it under 12,000 characters — past that it is cut.

## Stack

Python 3.14 + uv (Typer CLI, FastAPI, MCP). The gate is `bin/check` (`uv run ruff check . && uv run ruff format --check . && uv run mypy . && TMPDIR=/tmp uv run pytest tests/ -n 2 -q --timeout=120`): a change that does not pass it is not proven, whatever its description says.

## Review conventions
- Hold every change to the documented gate: `ruff check .`, `ruff format --check .`, `mypy .` and `pytest`, all on the whole tree.
- Require type hints on every new function and a Google-style docstring on public APIs.
- Reject a source file over 500 lines; ask for a split by responsibility instead.
- Require the mirrored test under `tests/<same path>` for every module touched.
- Treat the state directory layout (`.claude-task-master/`) and the packaged wrapper (`src/claude_task_master/bin/claudetm`) as public contracts; changing either is a breaking change.
- Require the version to move in all four places when a release is cut (pyproject.toml, `__init__.py`, `bin/claudetm`, `src/claude_task_master/bin/claudetm`).
- Reject any change that lets a worker commit, stage, branch or push — only the lead runs git.
- Reject a change that widens the tolerated CI failures beyond `github/check_tolerance.py`.

## Gates that matter
- `Lint` (ruff check + ruff format --check + mypy), `Tests` (pytest) and `Build & CLI Smoke Test` (uv build, `claudetm --help`, `claudetm doctor`, `claudetm status`) decide a pull request.
- "Proven" means the full gate ran on the branch, with `mypy .` over the whole tree — `mypy src` is not the gate.
- A narrowed or deselected test run does not count as proven.
- A behaviour change in the work loop needs a test that pins it, not a comment.
- Keep a PR to one concern; the repo's own `/feature` command caps a PR around 110–120 files because CodeRabbit refuses above 150.

## Never flag
- Formatting and import order that `ruff format` and ruff-isort own.
- Markdown code blocks: ruff deliberately excludes `*.md`; do not ask for a sample to be reflowed.
- The runtime state directory `.claude-task-master/` (gitignored) and the generated `coding-style.md` / `release.md`.
- `bin/claudetm` and `src/claude_task_master/bin/claudetm` being two copies — `scripts/sync_version.py` keeps their `SCRIPT_VERSION` in sync.
- The mypy overrides for `claude_agent_sdk`, `mcp`, `fastapi`, `uvicorn`, `passlib` and `anthropic` — third-party stubs are absent by design.
- The `Co-Authored-By` trailer in commit messages.
- A local gate run with `-n 2` workers and `--timeout=120`; CI uses `-n auto --timeout=120` and a shared box caps parallelism — the smaller local worker count is deliberate, not a defect.
