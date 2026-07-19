"""Work Session Prompts for Claude Task Master.

This module contains prompts for the work phase where Claude
executes tasks, makes changes, and creates PRs.
"""

from __future__ import annotations

from .prompts_base import PromptBuilder


def build_work_prompt(
    task_description: str,
    context: str | None = None,
    pr_comments: str | None = None,
    file_hints: list[str] | None = None,
    required_branch: str | None = None,
    create_pr: bool = True,
    push_only: bool = False,
    pr_group_info: dict | None = None,
    target_branch: str = "main",
    coding_style: str | None = None,
) -> str:
    """Build the work session prompt.

    Args:
        task_description: The current task to execute.
        context: Optional accumulated context.
        pr_comments: Optional PR review comments to address.
        file_hints: Optional list of relevant files to check.
        required_branch: Optional branch name the agent should be on.
        create_pr: If True, instruct agent to create PR. If False, commit only.
        push_only: If True, push the commit but do NOT create a PR — for fixing
            an existing PR. Overrides create_pr.
        pr_group_info: Optional dict with PR group context:
            - name: PR group name
            - completed_tasks: List of completed task descriptions in this group
            - remaining_tasks: Number of tasks remaining after current
        target_branch: The target branch for rebasing (default: "main").
        coding_style: Optional coding style guide to follow.

    Returns:
        Complete work session prompt.
    """
    branch_info = ""
    if required_branch:
        branch_info = f"\n\n**Current Branch:** `{required_branch}`"
        if required_branch in ("main", "master"):
            branch_info += (
                "\nYou are on main/master — create a feature branch before making changes."
            )

    builder = PromptBuilder(
        intro=f"""You are Claude Task Master executing a SINGLE task.

## Current Task

{task_description}{branch_info}

Focus on THIS task only — don't work ahead. Deliver HIGH QUALITY work; follow project instructions.

Refs: plan `.claude-task-master/plan.md` · progress `.claude-task-master/progress.md`

## Output Style

Terse. No filler, pleasantries, or narration. Don't announce actions — take them.
→ for flow, | for alternatives. Fragments fine.
Code, commits, PRs, JSON: proper syntax.
Status compressed: "added auth middleware → tests pass → 2 files changed".
Completion report: 3-5 lines. What changed, not how."""
    )

    # PR Group context - show what's already done in this PR
    if pr_group_info:
        pr_name = pr_group_info.get("name", "Default")
        completed = pr_group_info.get("completed_tasks", [])
        remaining = pr_group_info.get("remaining_tasks", 0)
        branch = pr_group_info.get("branch")
        branch_mandated = pr_group_info.get("branch_mandated", False)

        group_lines = [f"**PR Group:** {pr_name}"]
        if branch and branch_mandated:
            group_lines.append(
                f"**Branch (required):** use `{branch}` for all work in this run. "
                f"If it does not exist yet, create it (`git checkout -b {branch}`). "
                f"Do NOT invent a different branch name. For an additional PR in this run, "
                f"suffix it (e.g. `{branch}-2`) so PRs never collide."
            )
        elif branch:
            group_lines.append(f"**Branch:** `{branch}`")

        if completed:
            group_lines.append("\n**Already completed in this PR:**")
            for task in completed:
                group_lines.append(f"- ✓ {task}")

        if remaining > 0:
            group_lines.append(f"\n**Tasks remaining after this one:** {remaining}")
        else:
            group_lines.append("\n**This is the LAST task in this PR group.**")

        builder.add_section("PR Group Context", "\n".join(group_lines))

    # Context section
    if context:
        builder.add_section("Context", context.strip())

    # Coding style section - concise guide to follow
    if coding_style:
        builder.add_section(
            "Coding Style (MUST FOLLOW)",
            f"""Follow these project conventions:

{coding_style.strip()}""",
        )

    # File hints
    if file_hints:
        files_list = "\n".join(f"- `{f}`" for f in file_hints[:10])  # Limit to 10
        builder.add_section(
            "Relevant Files",
            f"""Start by reading these files:
{files_list}

For CI logs: Grep for `FAIL|Error:` first, then read only the matching files — never read a whole
job's logs, it overflows context.""",
        )

    # PR comments to address
    if pr_comments:
        builder.add_section(
            "PR Review Feedback",
            f"""Address this review feedback:

{pr_comments}

Grep for locations → Read relevant files to understand context → make changes if you agree, or
explain why not → run tests → commit.""",
        )

    # Execution guidelines - three modes:
    #   push_only: fix an existing PR (commit + push, no `gh pr create`)
    #   create_pr: full workflow (commit + push + create PR)
    #   else:     commit-only (more tasks remain in PR group)
    if push_only:
        execution_content = _build_push_only_execution(target_branch=target_branch)
    elif create_pr:
        execution_content = _build_full_workflow_execution(target_branch=target_branch)
    else:
        execution_content = _build_commit_only_execution()

    builder.add_section("Execution", execution_content)

    # Completion summary - different requirements based on workflow mode
    if push_only:
        completion_content = """**After completing THIS task, STOP.**

**You MUST commit AND push to update the existing PR (CI re-runs on push).**

Report (keep it short):
- **Changes:** What was done (1-2 sentences)
- **Tests:** Pass/fail summary
- **Commit:** hash (REQUIRED)
- **Pushed:** confirm `git push` succeeded (REQUIRED)
- **Blockers:** if any

PR already exists — do NOT run `gh pr create`, but you MUST push. Don't say "TASK COMPLETE" until the push has succeeded.

End with: `TASK COMPLETE`"""
    elif create_pr:
        completion_content = """**After completing THIS task, STOP.**

**You MUST push and create a PR before reporting completion.**

Report (keep it short):
- **Changes:** What was done (1-2 sentences)
- **Tests:** Pass/fail summary
- **Commit:** hash (REQUIRED)
- **PR:** URL (REQUIRED)
- **Blockers:** if any

Don't say "TASK COMPLETE" until you have the PR URL.

End with: `TASK COMPLETE`"""
    else:
        completion_content = """**After completing THIS task, STOP.**

**Commit your work but DO NOT create a PR yet.**

Report (keep it short):
- **Changes:** What was done (1-2 sentences)
- **Tests:** Pass/fail summary
- **Commit:** hash (REQUIRED)
- **Blockers:** if any

Do NOT push or create a PR — more tasks remain in this PR group.

End with: `TASK COMPLETE`"""

    builder.add_section("On Completion - STOP", completion_content)

    return builder.build()


def _build_full_workflow_execution(target_branch: str = "main") -> str:
    """Build execution instructions for full workflow (commit + push + PR).

    Args:
        target_branch: The target branch to rebase onto (e.g., main, master, develop).
    """
    return f"""**1. Check git status first** — `git status`. On main/master, create a feature branch; on a feature branch, continue there.

**2. Understand the task** — Read files before modifying. Check existing patterns; identify which tests to run.

**3. Read project conventions FIRST** — Check the repository root for `CLAUDE.md` (coding standards you MUST follow); also `.claude/instructions.md`, `CONTRIBUTING.md`, `.cursorrules`.

**4. Make changes** — Edit/Write files. Follow the coding style from `CLAUDE.md`. Match existing patterns. Stay focused on this task.

**5. Verify work** — run the repo's tests + lint (whatever it uses):
```bash
pytest                   # Python
npm test                 # JS
ruff check . && mypy .   # Python lint/types
eslint . && tsc          # JS lint/types
```

**6. Commit** —
```bash
git add -A -- ':!.claude-task-master' && git commit -m "$(cat <<'EOF'
type: Brief description (≤50 chars)

- What changed / why

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```
The `':!.claude-task-master'` pathspec above (and `.git/info/exclude`, written at init) keeps orchestrator state out of the commit. Never add it manually.

**7. Rebase onto {target_branch} before pushing** — `git fetch origin {target_branch} && git rebase origin/{target_branch}`. Other PRs may have merged; rebasing now prevents conflicts in the PR. Resolve any conflicts keeping both sides' intent, then re-run tests.

**8. Push and Create PR** (REQUIRED) —
```bash
git push -u origin HEAD
gh pr create --title "type: description (≤70 chars)" --body "..." --label "claudetm"
```
If the label doesn't exist, create it and retry. PR body = 2-4 bullets of what/why, no filler.

Your work is NOT complete until you have a PR URL.

**STOP AFTER PR CREATION.** Do not wait for CI, check status, or merge — the orchestrator handles that."""


def _build_push_only_execution(target_branch: str = "main") -> str:
    """Build execution instructions for fixing an existing PR (commit + push, no PR create).

    Args:
        target_branch: The target branch name (for context only — we do NOT rebase
            during a fix session because rebasing would rewrite already-reviewed
            commits and disrupt the PR's review threads).
    """
    return f"""**1. Check git status first** — `git status`. You should be on the PR's feature branch (not {target_branch}/master/develop). If on a default branch, STOP — the workflow is wrong.

**2. Understand the task** — Read the CI logs / PR comments referenced above and the relevant files before modifying. Identify tests/lint to run.

**3. Read project conventions FIRST** — Check the repository root for `CLAUDE.md` (coding standards you MUST follow); also `.claude/instructions.md`, `CONTRIBUTING.md`, `.cursorrules`.

**4. Make changes** — Edit/Write files. Follow the coding style from `CLAUDE.md`. Match existing patterns. Stay focused on the issues raised.

**5. Verify work** — run the repo's tests + lint:
```bash
pytest                   # Python
npm test                 # JS
ruff check . && mypy .   # Python lint/types
eslint . && tsc          # JS lint/types
```

**6. Commit** —
```bash
git add -A -- ':!.claude-task-master' && git commit -m "$(cat <<'EOF'
fix: Brief description (≤50 chars)

- What changed / why

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```
The `':!.claude-task-master'` pathspec above (and `.git/info/exclude`, written at init) keeps orchestrator state out of the commit. Never add it manually.

**7. Push to update the existing PR** (REQUIRED) — `git push origin HEAD`. CI re-runs on push. Do NOT run `gh pr create` (the PR already exists). NEVER rebase onto {target_branch} during a fix — it rewrites already-reviewed commits and breaks the PR's review threads. If push is rejected: `git pull --rebase origin HEAD`, resolve conflicts, re-test, push.

**STOP AFTER PUSH.** Do not wait for CI, check status, or merge — the orchestrator handles that."""


def _build_commit_only_execution() -> str:
    """Build execution instructions for commit-only workflow (more tasks in group)."""
    return """**1. Check git status first** — `git status`. On main/master, create a feature branch; on a feature branch, continue there.

**2. Understand the task** — Read files before modifying. Check existing patterns; identify which tests to run.

**3. Read project conventions FIRST** — Check the repository root for `CLAUDE.md` (coding standards you MUST follow); also `.claude/instructions.md`, `CONTRIBUTING.md`, `.cursorrules`.

**4. Make changes** — Edit/Write files. Follow the coding style from `CLAUDE.md`. Match existing patterns. Stay focused on this task.

**5. Verify work** — run the repo's tests + lint:
```bash
pytest                   # Python
npm test                 # JS
ruff check . && mypy .   # Python lint/types
eslint . && tsc          # JS lint/types
```

**6. Commit** —
```bash
git add -A -- ':!.claude-task-master' && git commit -m "$(cat <<'EOF'
type: Brief description (≤50 chars)

- What changed / why

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```
The `':!.claude-task-master'` pathspec above (and `.git/info/exclude`, written at init) keeps orchestrator state out of the commit. Never add it manually.

**7. DO NOT create PR yet** — More tasks remain in this PR group. Just commit; do NOT push or create a PR. The orchestrator will tell you when to open the PR (after all tasks in the group are done)."""
