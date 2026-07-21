# claude-task-master

`claudetm` — an autonomous task orchestration system that keeps Claude working until a stated
goal is achieved. It plans, executes, and verifies work through a PR-based workflow: it opens
pull requests, pulls CI failures and review comments together, persists run state so it can be
interrupted and resumed, and exposes a mailbox so a plan can be updated mid-run (via CLI, REST,
or MCP) and so multiple instances can coordinate. It serves developers who want long-running
autonomous coding sessions on their own repos. Note: the successor project `ai-task-master`
describes this repo as deprecated.

- **Stack:** Python ≥ 3.12, packaged with setuptools and managed with `uv`; published to PyPI
  as `claude-task-master`. Built on the Claude Agent SDK (`claude-agent-sdk`), with Typer for
  the CLI, Pydantic, Rich, and httpx. Auth uses OAuth credentials from
  `~/.claude/.credentials.json`. Tooling: pytest, ruff, mypy. A Dockerfile and
  docker-compose.yml are present. Run state lives in a per-project `.claude-task-master/`
  directory.
- **Key commands:** `uv sync --all-extras` then `uv run claudetm doctor` for a dev install;
  `uv tool install --force --reinstall .` for a global install. Dev loop: `pytest`,
  `ruff check . && ruff format .`, `mypy .`. Usage: `claudetm start "<goal>"`,
  `claudetm status`, `claudetm plan`, `claudetm resume "<message>"`, `claudetm clean -f`,
  `claudetm merge-pr`.
- **Layout:**
  - `src/claude_task_master/` — all application code (credential manager, state manager, agent
    wrapper, planner, plan updater, work-loop orchestrator, mailbox, PR context manager, logger;
    model routing config in `core/config.py`)
  - `tests/` — test suite; `coverage.xml` / `coverage_html/` are checked-in coverage output
  - `scripts/` — setup helpers including `setup-hooks.sh` (git pre-commit hooks)
  - `docs/` + `examples/` — documentation and usage examples
  - `bin/`, `Dockerfile`, `docker-compose.yml` — entrypoints and container setup
  - `CHANGELOG.md`, `RELEASING.md`, `VERIFICATION.md` — release process
- **State as of 2026-07-21:** branch `main`; working tree was clean when this note was written.
  Version in `pyproject.toml` was 0.1.63.
