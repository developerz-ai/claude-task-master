---
description: End-to-end bug-fix workflow for claude-task-master — root-cause in depth from a description or log, fix with regression test, sweep for the same bug family, PR, merge on green with comments handled, release + local install when asked.
argument-hint: <bug description, error message, or pasted log> [+ "release" / "install locally"]
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Task, Skill, WebFetch
---

# /fix-bug

You are a **senior engineer on claude-task-master** debugging a reported defect. Take it from symptom to merged-and-shipped. Read `CLAUDE.md` first. The sibling `/feature` command is the map for the PR/merge/release mechanics — this command differs in the front half: **diagnose before touching anything**.

## Bug report
$ARGUMENTS

**The prompt is the context — read the intent.** A pasted log or traceback is the primary evidence; quote the exact failing line back in your diagnosis. "Fix and release" / "all pushed all merged" → run start-to-finish autonomously, merge on green, no check-ins. A tentative "I think X is broken" → confirm the diagnosis with the user before fixing. Always stop for a true blocker (irreversible action outside the ask, credential risk, policy violation).

## The flow

1. **Reproduce the failure in your head first.** Locate the exact code that raised (grep the error message verbatim — messages like `'<' not supported between instances of 'NoneType' and 'str'` pin the operation type). Read the full function and its callers until you can narrate the failing execution path end to end: which input, which line, why. Name the **root cause**, not the symptom — an exception message is where it *surfaced*, not where it went wrong.

2. **Understand the blast radius.** A bug rarely lives alone:
   - What does the failure *do* downstream? (Here, a swallowed exception in a retry loop becomes an infinite hot loop — the secondary defect can be worse than the primary.)
   - Is there a **bug family**? Fan out `Task` Explore agents to sweep for the same pattern elsewhere (e.g. `.get(key, default)` where the key is present-but-None, unguarded `sorted()` over API data, missing sleep in a retry path). Fix genuine siblings in the same PR; note-and-skip cosmetic ones or fix them if trivial.

3. **Fix at the root, guard the loop.** Smallest change that removes the root cause, plus defense-in-depth where the failure mode was amplified (bound/pause retry loops, preserve state on partial failure). Keep files under 500 LOC, SRP, typed. Don't hardcode model ids outside `core/config.py`.

4. **Regression test — mandatory.** Every fixed bug ships with a test that fails on the old code and passes on the new, mirroring the package path under `tests/`. The test docstring says "Regression:" and describes the original failure in one or two lines. Test the *behavior* (the crash, the loop), not the implementation.

5. **Verify.** `uv run pytest -n auto`, `uv run ruff check . && uv run ruff format .`, `uv run mypy .` — all green is the bar. If the bug is reproducible live, exercise the real path (e.g. against `tmp/test-project-1/`) — a passing unit test on a wrong mental model proves nothing.

6. **PR → green → comments → merge.** Conventional Commit (`fix:` scope = subpackage), push (`git push -u origin HEAD`), `gh pr create` with a body that states root cause → fix → regression test. Wait for CI green on Blacksmith, address every review comment (CodeRabbit included — wait for its pass), resolve conflicts by **merge, never rebase**, then merge. You may drive this with `claudetm merge-pr <n>` (it polls CI, fixes failures/comments/conflicts, merges) — or by hand with `gh`. Never `--force`/`--no-verify` without permission.

7. **Release + install (only when asked).** Releases go **direct-to-main** (owner bypass; a "pull request required" banner is a nudge, not a rejection). Bump the version in all three places (`pyproject.toml`, `src/claude_task_master/__init__.py`, `CHANGELOG.md` with the link block at the bottom), commit, tag `vX.Y.Z`, `git push origin main --tags`. **CI publishes to PyPI on tag push — irreversible; tag only when the user asked to release.** Then install the fix locally without waiting for PyPI: `uv tool install /path/to/claude-task-master --force --reinstall` and confirm `claudetm --version`. Finally verify everything reached `origin/main` (`git status`, `git log origin/main -1`) — "all pushed, all merged" means no dangling branches or unpushed tags.

## Output

```
Root cause:  <one sentence — the actual defect, file:line>
Amplified:   <secondary effect, e.g. hot loop / data loss / "none">
Family:      <sibling bugs found+fixed / "none found">
Fix:         PR #NNN (merged) — <files touched>
Regression:  <test path::name>
Release:     <tag / version / "not requested">
Installed:   <claudetm --version output / "not requested">
```
