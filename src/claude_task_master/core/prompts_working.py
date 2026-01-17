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
    pr_group_info: dict | None = None,
) -> str:
    """Build the work session prompt.

    Args:
        task_description: The current task to execute.
        context: Optional accumulated context.
        pr_comments: Optional PR review comments to address.
        file_hints: Optional list of relevant files to check.
        required_branch: Optional branch name the agent should be on.
        create_pr: If True, instruct agent to create PR. If False, commit only.
        pr_group_info: Optional dict with PR group context:
            - name: PR group name
            - completed_tasks: List of completed task descriptions in this group
            - remaining_tasks: Number of tasks remaining after current

    Returns:
        Complete work session prompt.
    """
    branch_info = ""
    if required_branch:
        branch_info = f"\n\n**Current Branch:** `{required_branch}`"
        if required_branch in ("main", "master"):
            branch_info += (
                "\n⚠️ You are on main/master - create a feature branch before making changes!"
            )

    builder = PromptBuilder(
        intro=f"""You are Claude Task Master executing a SINGLE task.

## Current Task

{task_description}{branch_info}

**Focus on THIS task only. Do not work ahead to other tasks.**

🎯 **Deliver HIGH QUALITY work. Follow project instructions.**

📋 **Full plan:** `.claude-task-master/plan.md` | **Progress:** `.claude-task-master/progress.md`"""
    )

    # PR Group context - show what's already done in this PR
    if pr_group_info:
        pr_name = pr_group_info.get("name", "Default")
        completed = pr_group_info.get("completed_tasks", [])
        remaining = pr_group_info.get("remaining_tasks", 0)
        branch = pr_group_info.get("branch")

        group_lines = [f"**PR Group:** {pr_name}"]
        if branch:
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

    # File hints
    if file_hints:
        files_list = "\n".join(f"- `{f}`" for f in file_hints[:10])  # Limit to 10
        builder.add_section(
            "Relevant Files",
            f"Start by reading these files:\n\n{files_list}",
        )

    # PR comments to address
    if pr_comments:
        builder.add_section(
            "PR Review Feedback",
            f"""Address this review feedback:

{pr_comments}

**For each comment:**

1. **Explore thoroughly first** - Read the relevant files and understand the context
   before making any changes. Don't rush to implement.

2. **If you agree** - Make the requested change, run tests, and commit.

3. **If you disagree** - Do NOT implement the change. Instead:
   - Explain your reasoning clearly and respectfully
   - Provide technical justification for your approach
   - This helps the reviewer learn and understand your perspective
   - The reviewer can then decide whether to push back or accept

4. Run tests after any changes
5. Commit referencing the feedback""",
        )

    # Execution guidelines - conditional based on create_pr flag
    if create_pr:
        execution_content = _build_full_workflow_execution()
    else:
        execution_content = _build_commit_only_execution()

    builder.add_section("Execution", execution_content)

    # Completion summary
    builder.add_section(
        "On Completion - STOP",
        """**After completing THIS task, STOP.**

**IMPORTANT: Always commit your work before reporting completion.**
```bash
# 1. Commit your changes (.claude-task-master/ is auto-gitignored)
git add -A && git commit -m "task: Brief description of what was done"
```

Report:
1. What was completed
2. Tests run and results
3. Files modified
4. Commit hash (REQUIRED - must have committed)
5. Any blockers

End your response with:
```
TASK COMPLETE
```

**The orchestrator will start a NEW session for the next task.**""",
    )

    return builder.build()


def _build_full_workflow_execution() -> str:
    """Build execution instructions for full workflow (commit + push + PR)."""
    return """**1. Check git status first**
```bash
git status
```
- Know where you are before making changes
- If on main/master, create a feature branch first
- If already on a feature branch, continue working there

**2. Understand the task**
- Read files before modifying
- Check existing patterns
- Identify tests to run

**3. Make changes**
- Edit existing files, Write new files
- Follow project coding style
- Stay focused on current task

**4. Verify work**
```bash
# Common verification commands
pytest                    # Python tests
npm test                  # JS tests
ruff check . && mypy .   # Python lint/types
eslint . && tsc          # JS lint/types
```

**5. Commit properly**
```bash
git add -A && git commit -m "$(cat <<'EOF'
type: Brief description (50 chars)

- What changed
- Why needed

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

**Note:** The `.claude-task-master/` directory is automatically gitignored - it contains
orchestrator state files that should never be committed.

**6. Push and Create PR** (REQUIRED)
```bash
git push -u origin HEAD
gh pr create --title "type: description" --body "..." --label "claudetm"
```
If label doesn't exist, create it and retry.

**PR title format:** `type: Brief description`

⚠️ **Your work is NOT done until pushed and in a PR!**

**STOP AFTER PR CREATION - DO NOT:**
- ❌ Wait for CI (`sleep`, `watch`, polling)
- ❌ Check CI status (`gh pr checks`, `gh pr view`)
- ❌ Monitor PR status
- ❌ Merge the PR

**The orchestrator handles CI/reviews/merge automatically.**

**7. Log File Best Practices**
- For log/progress files, use APPEND mode (don't read entire file)
- Example: `echo "message" >> progress.md` instead of Read + Write
- This avoids context bloat from reading large log files"""


def _build_commit_only_execution() -> str:
    """Build execution instructions for commit-only workflow (more tasks in group)."""
    return """**1. Check git status first**
```bash
git status
```
- Know where you are before making changes
- If on main/master, create a feature branch first
- If already on a feature branch, continue working there

**2. Understand the task**
- Read files before modifying
- Check existing patterns
- Identify tests to run

**3. Make changes**
- Edit existing files, Write new files
- Follow project coding style
- Stay focused on current task

**4. Verify work**
```bash
# Common verification commands
pytest                    # Python tests
npm test                  # JS tests
ruff check . && mypy .   # Python lint/types
eslint . && tsc          # JS lint/types
```

**5. Commit properly**
```bash
git add -A && git commit -m "$(cat <<'EOF'
type: Brief description (50 chars)

- What changed
- Why needed

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

**Note:** The `.claude-task-master/` directory is automatically gitignored - it contains
orchestrator state files that should never be committed.

**6. DO NOT create PR yet**

⚠️ **More tasks remain in this PR group. Just commit, do NOT push or create PR.**

The orchestrator will tell you when to create the PR (after all tasks in this group are done).

**7. Log File Best Practices**
- For log/progress files, use APPEND mode (don't read entire file)
- Example: `echo "message" >> progress.md` instead of Read + Write
- This avoids context bloat from reading large log files"""
