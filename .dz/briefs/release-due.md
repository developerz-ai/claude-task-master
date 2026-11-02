# Brief: is a release due?

Weekday checkup fired by `schedules: release-due`. This brief decides *when*; the steps below are the *how*.

## Decide

```bash
git fetch --tags --unshallow origin 2>/dev/null || git fetch --tags origin
last=$(git describe --tags --abbrev=0 --match 'v[0-9]*' origin/main)
git log --format='%h %cI %s' "$last"..origin/main -- src pyproject.toml uv.lock requirements.txt bin Dockerfile
grep -m1 '^version' pyproject.toml
```

The pathspec names what reaches users. Prose, tests, CI and docs ship nothing.

| Window | Do |
|---|---|
| a command above failed | no verdict: surface it, file nothing |
| empty | nothing |
| the stamped version is already ahead of `$last` | nothing: a release is in flight, watch `publish.yml` |
| the oldest shipping commit is under 24 h old | nothing: its author may still release it |
| `main`'s latest `ci.yml` push run is not `success` | nothing: `health` owns a red `main` |
| a breaking change in the window | no release ask. If no open issue titled `Major release pending` exists, file one for a maintainer, with no release steps |
| otherwise | one ask, **Release `<next>`**, listing the commits |

`<next>`: a `feat` subject in the window is a minor, anything else a patch.

## The ask

File nothing if an open issue title is exactly `Release <next>`, or an open PR is already that release. Body, for the box that takes it:

1. Re-run Decide on fresh `main`; still due, or stop.
2. `python scripts/bump_version.py --set <next>`, then set `SCRIPT_VERSION` in `bin/claudetm` and `src/claude_task_master/bin/claudetm` (`CLAUDE.md` § Releasing), and write the `CHANGELOG.md` section over the window. Nothing else in the diff.
3. Run the gate, then one PR titled `chore: Release v<next>`. It merges on green like any PR.
4. After it merges: `git fetch origin && git tag v<next> <merge sha> && git push origin v<next>`, only after `git show <merge sha>:pyproject.toml` shows `<next>`.
5. Watch `publish.yml` to the end. A failure is an issue for a maintainer.

Never re-tag, move or delete a tag, and never publish by hand. A failed publish is an issue for a maintainer; the fix ships as the next patch.

## Rows

- `decide-commands-ok`: Every command in Decide succeeded; a failed command is no verdict — surface it, file nothing.
- `window-not-empty`: The window between `$last` and `origin/main`, over the pathspec in Decide, holds at least one shipping commit.
- `no-release-in-flight`: The stamped version in `pyproject.toml` is not ahead of `$last`; a version already ahead means a release is in flight — watch `publish.yml`.
- `oldest-shipping-commit-24h`: The oldest shipping commit in the window is at least 24 h old; a younger one may still be released by its author.
- `main-green`: The latest `ci.yml` push run on `main` is `success`; a red `main` belongs to `health`.
- `no-breaking-change`: The window carries no breaking change; one means no release ask, and a `Major release pending` issue for a maintainer.
- `release-due`: Every condition above holds — the window is not blocked, so it owes a release, and one ask `Release <next>` lists the commits.
