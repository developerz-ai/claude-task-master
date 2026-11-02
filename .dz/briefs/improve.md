# Brief: monthly improvement

Fired every Monday by `schedules: improve`. **Act only on the first Monday of the month:**
`[ "$(date -u +%-d)" -le 7 ]`. On any other Monday stop here, file nothing, open nothing.

Once a month, leave claudetm measurably better. `CLAUDE.md` binds every change, and `non_goals` in the policy file are off limits. A red `main`,
a missing publish and a stuck Dependabot PR belong to `health`.

## Signals

| Signal | Command |
|---|---|
| the gate on fresh `main` | `ruff check . && ruff format --check . && mypy . && pytest` |
| dependency majors | `uv tree --outdated` |
| open bugs | `gh issue list --state open --label bug --json number,title,url` |

## Pick at most three, in this order

1. Anything the gate found broken or flaky: the root cause, never a retry or a skip.
2. Dependency majors, starting with `claude-agent-sdk`, one per PR.
3. Open bugs, each starting from a test that fails on `main`.
4. `CLAUDE.md` and README claims that no longer match the code, then dead code.

## Ship

One small PR per improvement, its evidence in the body, `ruff check . && ruff format --check . && mypy . && pytest` green first. Never bump the version or touch release automation here.
Check no open PR or issue already covers it. If nothing is worth changing, do nothing: no empty PRs, no churn.
