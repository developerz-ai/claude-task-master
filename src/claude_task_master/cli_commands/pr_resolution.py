"""Resolving *which* PR ``claudetm merge-pr`` operates on.

Three inputs are accepted — an explicit number/URL, the current branch's PR, or
(with ``--create-pr``) a branch that has commits but no PR yet. The last one is
opt-in on purpose: opening a PR publishes work, which is not something a command
the user ran to *merge* something should do behind their back.
"""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING

import typer

from ..core import console
from .fix_session import get_current_branch, pending_changes_summary
from .merge_finalize import git_failure, run_git

if TYPE_CHECKING:
    from ..github import GitHubClient

DEFAULT_BRANCHES = {"main", "master", "develop", "development"}

PR_URL_PATTERN = re.compile(r"/pull/(\d+)")


def parse_pr_input(pr_input: str | None) -> int | None:
    """Parse a PR number from input (number, ``#number``, or URL).

    Args:
        pr_input: PR number as string, GitHub PR URL, or None.

    Returns:
        PR number as int, or None if not provided/unparseable.
    """
    if pr_input is None:
        return None

    if pr_input.isdigit():
        return int(pr_input)

    match = PR_URL_PATTERN.search(pr_input)
    if match:
        return int(match.group(1))

    if pr_input.startswith("#") and pr_input[1:].isdigit():
        return int(pr_input[1:])

    return None


def validate_not_default_branch() -> None:
    """Error if currently on a default branch (main, master, etc.)."""
    branch = get_current_branch()
    if branch and branch in DEFAULT_BRANCHES:
        console.error(f"Cannot run merge-pr from default branch '{branch}'.")
        console.info("Checkout the PR branch first: git checkout <branch>")
        raise typer.Exit(1)


def open_pr_for_current_branch(branch: str) -> int | None:
    """Push the current branch and open a PR for it with ``gh pr create --fill``.

    Loud by design: this is the one outward-facing action ``merge-pr`` can take,
    so it announces itself before and after.

    Args:
        branch: The current branch name (never a default branch).

    Returns:
        The new PR number, or None if the branch could not be pushed or the PR
        could not be created.
    """
    console.warning(f"No PR exists for branch '{branch}'.")
    console.warning("--create-pr was passed, so a PULL REQUEST WILL BE OPENED for this branch.")

    pending = pending_changes_summary()
    if pending:
        console.warning("Uncommitted changes will NOT be part of the PR:")
        for line in pending.splitlines():
            console.detail(f"  {line}")

    console.info(f"Pushing {branch} to origin...")
    push = run_git("push", "-u", "origin", "HEAD", timeout=180)
    if push is None or push.returncode != 0:
        console.error(f"Could not push {branch}: {git_failure(push)}")
        return None

    console.info("Creating the pull request (gh pr create --fill)...")
    try:
        created = subprocess.run(
            ["gh", "pr", "create", "--fill"],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as e:
        console.error(f"Could not create a PR for {branch}: {e}")
        return None

    output = f"{created.stdout}\n{created.stderr}".strip()
    if created.returncode != 0:
        console.error(f"Could not create a PR for {branch}: {output or 'gh pr create failed'}")
        return None

    match = PR_URL_PATTERN.search(output)
    if not match:
        console.error(f"Created a PR but could not read its number from gh output: {output!r}")
        return None

    pr_number = int(match.group(1))
    console.success(f"OPENED PR #{pr_number} for {branch}")
    for line in output.splitlines():
        if line.strip().startswith("http"):
            console.detail(f"  {line.strip()}")
    return pr_number


def resolve_pr_number(
    github_client: GitHubClient,
    pr_input: str | None,
    create_pr: bool = False,
) -> int:
    """Decide which PR to work on, optionally opening one for the current branch.

    Args:
        github_client: GitHub client for API calls.
        pr_input: Raw CLI argument (number, URL, or None).
        create_pr: Open a PR when the current branch has none.

    Returns:
        The PR number to operate on.

    Raises:
        typer.Exit: If the input is unparseable, or no PR exists and none could
            (or may) be created.
    """
    pr_number = parse_pr_input(pr_input)

    if pr_input is not None and pr_number is None:
        console.error(f"Invalid PR input '{pr_input}'.")
        console.info("Use a PR number or PR URL, e.g. claudetm merge-pr 123")
        raise typer.Exit(1)

    if pr_number is not None:
        return pr_number

    pr_number = github_client.get_pr_for_current_branch()
    if pr_number is not None:
        console.success(f"Detected PR #{pr_number} for current branch")
        return pr_number

    branch = get_current_branch()
    if create_pr and branch and branch not in DEFAULT_BRANCHES:
        created = open_pr_for_current_branch(branch)
        if created is not None:
            return created
        raise typer.Exit(1)

    console.error("No PR found for current branch.")
    console.info("Specify a PR number: claudetm merge-pr 123")
    console.info("Or open one for this branch first: claudetm merge-pr --create-pr")
    raise typer.Exit(1)


__all__ = [
    "DEFAULT_BRANCHES",
    "open_pr_for_current_branch",
    "parse_pr_input",
    "resolve_pr_number",
    "validate_not_default_branch",
]
