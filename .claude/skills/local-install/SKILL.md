---
description: Verifying a local install of the package and its bash wrapper. Use for install, packaging, wrapper, entry point, console script.
applies: [python]
---

> House skill — established by dz-runner setup mode from this repo's own evidence, then owned by its maintainers. Correct it in place; setup never overwrites a skill that exists.

1. `uv sync --all-extras` -> a `.venv` whose `bin/` holds `claudetm`, `claudetm-py`, `claudetm-mcp`, `claudetm-server` -> fail -> stop if any is missing.
2. Install it the way a user gets it: `uv tool install --force --reinstall .` -> fail -> stop, the package does not build.
3. `./.venv/bin/claudetm --version` -> prints the bash-wrapper version and the package version; both must match `pyproject.toml`.
4. `./.venv/bin/claudetm --init-config` then `./.venv/bin/claudetm --show-config` -> the config file is created and read back.
5. `./.venv/bin/claudetm doctor` -> missing credentials are expected without a Claude login, but it must not crash.
6. `./.venv/bin/claudetm status` -> must not crash when no task state exists.
7. The wrapper that ships is `src/claude_task_master/bin/claudetm`; `bin/claudetm` is the repo-root copy -> after editing either, `python scripts/sync_version.py --check` -> fail -> stop on a mismatch.
