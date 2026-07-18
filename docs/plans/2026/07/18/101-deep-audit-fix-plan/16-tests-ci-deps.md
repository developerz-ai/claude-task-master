# 16 — Tests, CI install, dependency updates

> Part of [`overview.md`](overview.md). Depends on: none (test gaps can start anytime; write tests WITH the fix slices where they overlap).

## Top test gaps (ranked by risk — audit-verified zero coverage)
1. Model fallback chain + `MODEL_FALLBACK_MAP` + `fallback_model` wiring — ZERO tests → `tests/core/test_agent_models_fallback.py`.
2. Cross-parser checkbox consistency → `tests/core/test_plan_parsing.py` (property test; lands with 01).
3. `handle_releasing_stage`/`handle_release_fix_stage` — zero of the 61 workflow-stage tests cover release → `tests/core/test_workflow_stages_release.py`.
4. `core/prompts_release.py` — only prompts module without tests, and it has real parsers → `tests/core/test_prompts_release.py` (lands with 13).
5. `--prs` reaches the planning prompt → extend `test_prompts_planning.py`/`test_planner.py`.
6. `core/agent_message.py` MessageProcessor — untested stream-parsing hot path → `tests/core/test_agent_message.py` (lands with 12).
7. Profile CLI (add/use/remove/login) — zero tests; multi-account safety-relevant → `tests/cli_commands/test_profile.py` (lands with 11).
8. `core/config_loader.py` env precedence incl. `CLAUDETM_MODEL_FABLE` → `tests/core/test_config_loader.py`.
9. Repo setup tools per-function tests after the 15 split.
10. True SDK smoke path — `tests/integration/` is fully mocked (`MockClaudeAgentSDK`); nothing exercises the real subprocess boundary. Add one opt-in marked smoke test.

## Test-quality fixes
- `pyproject.toml:161` — global `--timeout=2` vs `time.sleep(1.1)` in test_state.py:1534 (+6 more sleeps) → flaky margin. Replace sleeps with monkeypatched clock/freezegun; drop forced `--cov` from `addopts` (slow local runs), move coverage to CI flags.
- Markers declared (`slow/integration/unit/property`) but unused — either apply `pytestmark` or delete; CI selects by path anyway.
- Brittle suites: `test_merger.py` asserts exact merged-prompt wording (~80 tests); orchestrator tests assert private attrs (`_task_runner` caching). Loosen to behavior.

## Dependency updates (user-requested)
- `pyproject.toml:27-31` — all 5 runtime deps lower-bound-only (`>=` no caps) — `uv tool install` floats majors. Add upper bounds (`typer`, `rich`, `httpx`, `pydantic`, `claude-agent-sdk`) and **bump minimums to current versions** (`uv lock --upgrade`, run full suite, then pin ranges). SDK bump: check changelog for `ResultMessage`/`parent_tool_use_id` fields used by 12 fixes.
- `pyproject.toml:209-212` — `[dependency-groups] dev` duplicates optional-dependencies pin — keep one.
- `pyproject.toml:204-206` — `[tool.uv.workspace] members = ["tmp/test-project-1"]` breaks `uv sync` for anyone without that dir. Remove.
- CI installs `.[dev,api]` only (`ci.yml:65,113,159`) — `tests/mcp/` runs solely via the SDK's transitive `mcp>=1.23`, while `[mcp]` extra pins `>=1.26`. Add `mcp` (or `.[all]`) to CI install.
- Python: classifiers + CI pin 3.12 only despite `requires-python >= 3.12` — add a 3.13 CI job or narrow requires-python.
- CI policy itself verified compliant (Blacksmith, concurrency, timeouts, publish `cancel-in-progress: false`) — no changes. **Do not touch publish workflows in this slice; publishes are irreversible.**

## Commands
- `uv lock --upgrade && uv sync --all-extras && pytest && ruff check . && mypy .`

## Done when
- Top-10 gaps have test files; suite passes with upgraded lock; no sleep-based flake margins; CI installs the extras it tests.
