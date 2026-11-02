---
description: Prove a change in developerz-ai/claude-task-master before committing or opening a pull request — the repo's own install, run and check commands. Use before every commit.
applies: [python]
---

# Verify a change in developerz-ai/claude-task-master

> House skill — established by dz-runner setup mode from this repo’s own
> detected commands. Correct it in place; setup never overwrites a skill that exists.

## The one gate

`bin/check` is the local gate, also invoked by the pre-commit hook. CI does not
invoke it: `.github/workflows/ci.yml` independently runs equivalent lint, test,
and PR-package commands. Keep this script aligned with those gates; a local pass
is evidence for the local environment, not a guarantee that CI will pass.

| Step | Command | What it is |
|------|---------|------------|
| install | `bin/setup` | Check host prerequisites, install missing apt packages as root or via non-interactive sudo, run mise install, select global uv@0.13 and python@3.14, sync all extras, then create the empty external profile volume. Each failed step stops setup. |
| run | `bin/dev` | `docker compose up --build --wait --wait-timeout 180` rebuilds the checkout and returns success only after health readiness. On developerz.ai runs, start it with code_bash_background when you need a running stack. |
| prove | `bin/check` | Whole-tree Ruff lint/format checks and mypy; CI-profile tests with coverage; distribution build and CLI help/doctor/status smoke checks (mapping below). |
| stop | `bin/stop` | docker compose stop — on developerz.ai runs, the platform runs this when your session ends — do not stop the stack yourself |

## Supported setup and startup

`bin/setup` supports Debian/Ubuntu-style hosts with Bash, dpkg and apt-get.
Install mise and Docker with the Compose plugin first, and put mise-managed tools
on PATH (including uv after `mise use`). Compose must support `up --wait` and
`--wait-timeout`. The caller needs Docker daemon access and, when apt packages
are missing, root privileges or working non-interactive `sudo -n` access.
Network access is needed for apt, mise and uv downloads. Setup retains the global
mise selections for uv 0.13 and Python 3.14 and installs all project extras.
It creates `claudetm-profiles` only after dependency sync succeeds; it never reads,
copies or provisions credentials.

`bin/dev` builds from the checked-out Compose build context rather than relying
on a potentially stale image. Compose waits for the existing REST `/health`
check; startup/health failures return nonzero, with a 180-second readiness wait
bound. This is not a wall-clock bound on the image build. Successful startup
leaves the stack detached. Compose mounts and credential isolation are unchanged:
health readiness does not require a personal login or an agent credential, and
is not proof that authenticated agent operations work.

`uv run pytest tests/test_bin_scripts.py -q --timeout=120` runs copied scripts in
a temporary repo using PATH-injected fake tools and an isolated HOME. It pins
ordering, root/sudo package installation, fail-fast behavior and dev rebuild/wait
arguments without invoking real apt, Docker, credentials or global mise changes.
These regressions are not evidence of real downloads, image builds or service
health. The coordinator's read-only survey could not execute real setup/dev;
record actual `bin/setup`, `bin/dev` and `bin/check` results separately when run
on a supported host. Do not claim real startup based on fake-tool tests alone.

## CI-to-local gate mapping

Use Python 3.14 and install all extras before proving a change:
`uv sync --all-extras --python 3.14` (also performed by `bin/setup`). CI selects
Python 3.14 and installs the editable package with `uv pip install -e ".[all]"`.

| CI job | Local equivalent in `bin/check` |
|--------|--------------------------------|
| Lint | `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy .` retain CI's whole-tree scope. |
| Tests | `HYPOTHESIS_PROFILE=ci` and `TMPDIR=/tmp uv run pytest tests/ -n 2 -q --timeout=120 --cov=claude_task_master --cov-report=xml:coverage.xml --cov-report=term-missing`. |
| Build & CLI Smoke Test (PRs only in CI) | `uv build --out-dir "$build_dir"`, then `uv run claudetm --help`, `uv run claudetm doctor`, and `uv run claudetm status`. |

Local tests deliberately use two workers rather than CI's `-n auto` to stay within
the shared box's resource ceiling. `TMPDIR=/tmp` remains scoped to pytest.
Coverage produces `.coverage` data, `coverage.xml`, and a terminal missing-lines
report. These artifacts are local evidence; the script does not upload them.

The build uses a unique temporary directory under `${TMPDIR:-/tmp}` and cleans it
on exit, including failed builds or smoke checks. Pre-existing `dist/` artifacts
are neither overwritten nor deleted. As in CI, the CLI probes run against the
editable project environment, not an installation of the built wheel.

Lint, formatter check, typecheck, tests, build, and CLI help must all succeed;
the script stops on failure. Only doctor and status use CI's explicit `|| true`
tolerance: missing credentials or project state may make them fail. Their output
remains visible, but a successful gate does not certify those two probes passed.

CI's test-output/build-artifact uploads and Codecov submission are reporting,
not local gates. Tag-triggered package/Docker publishing and manual test
publishing workflows are release operations, not part of this local PR gate.
No workflow restructuring is needed to keep these commands aligned.

## Rules

- Run every command from the repo root — the scripts `cd` there themselves.
- `bin/check` red is not a pull request. Fix the cause, never silence the gate.

## Exit codes `bin/check` must use

A coding box runs this gate before it commits, and it has to tell a FAILING change
from a gate it could not run — otherwise correct work is thrown away as if it were
red. Exit 1 cannot carry that difference, so one code is reserved:

| Exit | Means | What the platform does |
|------|-------|------------------------|
| 0 | the change passes | commit it |
| 75 | a resource the gate NEEDS is unreachable (a database, a service, a credential) — it refused to grade | refuse the commit, and blame the environment, never the change |
| any other non-zero | the gate ran and the change is red | refuse the commit, and blame the change |

- Guard preconditions FIRST and `exit 75` when one is unmet. `exit 1` there tells the
  platform your change is broken when it is your environment that is.
- Changed a dependency? Re-run `bin/setup` before `bin/check`, or you are proving a stale tree.
- Add the test that fails first, then the fix — a green run that never went red proves nothing.
