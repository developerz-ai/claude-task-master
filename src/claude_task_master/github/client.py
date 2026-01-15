"""GitHub Integration Layer - All GitHub operations via gh CLI and GraphQL API."""

import json
import subprocess
from typing import Any

from pydantic import BaseModel


class PRStatus(BaseModel):
    """PR status information."""

    number: int
    ci_state: str  # PENDING, SUCCESS, FAILURE, ERROR
    unresolved_threads: int
    check_details: list[dict[str, Any]]


class GitHubClient:
    """Handles all GitHub operations using gh CLI."""

    def __init__(self) -> None:
        """Initialize GitHub client."""
        self._check_gh_cli()

    def _check_gh_cli(self) -> None:
        """Check if gh CLI is installed and authenticated."""
        try:
            subprocess.run(
                ["gh", "auth", "status"],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError("gh CLI not authenticated. Run 'gh auth login' first.") from e
        except FileNotFoundError as e:
            raise RuntimeError("gh CLI not installed. Install from https://cli.github.com/") from e

    def create_pr(self, title: str, body: str, base: str = "main") -> int:
        """Create a new pull request."""
        result = subprocess.run(
            ["gh", "pr", "create", "--title", title, "--body", body, "--base", base],
            check=True,
            capture_output=True,
            text=True,
        )

        # Extract PR number from output
        # gh CLI outputs URL like: https://github.com/owner/repo/pull/123
        output = result.stdout.strip()
        pr_number = int(output.split("/")[-1])

        return pr_number

    def get_pr_status(self, pr_number: int) -> PRStatus:
        """Get PR status including CI checks and review comments."""
        # Get repository info
        repo_info = self._get_repo_info()
        owner, repo = repo_info.split("/")

        # Run GraphQL query
        query = """
        query($owner: String!, $repo: String!, $pr: Int!) {
          repository(owner: $owner, name: $repo) {
            pullRequest(number: $pr) {
              commits(last: 1) {
                nodes {
                  commit {
                    statusCheckRollup {
                      state
                      contexts(first: 50) {
                        nodes {
                          ... on CheckRun {
                            name
                            status
                            conclusion
                            detailsUrl
                          }
                        }
                      }
                    }
                  }
                }
              }
              reviewThreads(first: 100) {
                nodes {
                  isResolved
                  comments(first: 10) {
                    nodes {
                      author { login }
                      body
                      path
                      line
                    }
                  }
                }
              }
            }
          }
        }
        """

        result = subprocess.run(
            [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-F",
                f"owner={owner}",
                "-F",
                f"repo={repo}",
                "-F",
                f"pr={pr_number}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        data = json.loads(result.stdout)
        pr_data = data["data"]["repository"]["pullRequest"]

        # Parse CI status
        ci_state = "PENDING"
        check_details = []

        if pr_data["commits"]["nodes"]:
            commit = pr_data["commits"]["nodes"][0]["commit"]
            if commit["statusCheckRollup"]:
                ci_state = commit["statusCheckRollup"]["state"]
                contexts = commit["statusCheckRollup"]["contexts"]["nodes"]
                check_details = [
                    {
                        "name": ctx["name"],
                        "status": ctx["status"],
                        "conclusion": ctx.get("conclusion"),
                        "url": ctx.get("detailsUrl"),
                    }
                    for ctx in contexts
                ]

        # Count unresolved review threads
        unresolved = sum(
            1 for thread in pr_data["reviewThreads"]["nodes"] if not thread["isResolved"]
        )

        return PRStatus(
            number=pr_number,
            ci_state=ci_state,
            unresolved_threads=unresolved,
            check_details=check_details,
        )

    def get_pr_comments(self, pr_number: int, only_unresolved: bool = True) -> str:
        """Get PR review comments formatted for Claude."""
        # Get repository info
        repo_info = self._get_repo_info()
        owner, repo = repo_info.split("/")

        # Run GraphQL query
        query = """
        query($owner: String!, $repo: String!, $pr: Int!) {
          repository(owner: $owner, name: $repo) {
            pullRequest(number: $pr) {
              reviewThreads(first: 100) {
                nodes {
                  isResolved
                  comments(first: 10) {
                    nodes {
                      author { login }
                      body
                      path
                      line
                    }
                  }
                }
              }
            }
          }
        }
        """

        result = subprocess.run(
            [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-F",
                f"owner={owner}",
                "-F",
                f"repo={repo}",
                "-F",
                f"pr={pr_number}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        data = json.loads(result.stdout)
        threads = data["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]

        # Format comments
        formatted = []
        for thread in threads:
            if only_unresolved and thread["isResolved"]:
                continue

            for comment in thread["comments"]["nodes"]:
                author = comment["author"]["login"]
                is_bot = author.endswith("[bot]")
                bot_marker = " (bot)" if is_bot else ""

                formatted.append(
                    f"**{author}{bot_marker}** on {comment.get('path', 'PR')}:{comment.get('line', 'N/A')}\n"
                    f"{comment['body']}\n"
                )

        return "\n---\n\n".join(formatted)

    def merge_pr(self, pr_number: int) -> None:
        """Merge a pull request."""
        subprocess.run(
            ["gh", "pr", "merge", str(pr_number), "--squash", "--auto"],
            check=True,
        )

    def _get_repo_info(self) -> str:
        """Get current repository owner/name."""
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
