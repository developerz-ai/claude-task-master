"""StageHandlerBase — shared constants and __init__ for WorkflowStageHandler mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...github import GitHubClient
    from ..agent import AgentWrapper
    from ..pr_context import PRContextManager
    from ..state import StateManager
    from ..webhook_emitter import WebhookEmitter


class StageHandlerBase:
    """Base class for WorkflowStageHandler: constants, instance vars, __init__.

    All stage-specific methods live in the subclasses declared in the other
    modules of this package.  WorkflowStageHandler (defined in __init__.py)
    inherits the full chain and is the public API surface.
    """

    # CI polling configuration
    CI_POLL_INTERVAL = 10  # seconds between CI status checks
    CI_POLL_TIMEOUT = 7200  # seconds (120 min) before giving up on CI. Big CIs can run for
    # a long time; on timeout we block (error out) rather than merge a PR whose CI never
    # finished — unless --admin is set, which force-advances. See _ci_timeout_action.
    # Grace period before trusting the "No CI configured" fast path: GitHub can be
    # slow to register checks right after a push, so we only conclude there is no
    # CI once this many polls have run (or NO_CI_MIN_ELAPSED seconds have passed).
    NO_CI_MIN_POLLS = 2
    NO_CI_MIN_ELAPSED = 30  # seconds before trusting the no-CI fast path
    # Max consecutive "UNKNOWN" mergeable results / merge-status errors in
    # ready_to_merge before blocking for manual intervention.
    MAX_MERGE_UNKNOWN_ATTEMPTS = 6
    # Polls used to confirm a merge actually landed after merge_pr succeeds
    # (auto-merge enablement leaves the PR open until checks pass).
    MERGE_CONFIRM_POLLS = 6
    # Max consecutive CI-fix cycles before blocking for manual intervention.
    MAX_CI_FIX_ATTEMPTS = 3
    # Max conflict-resolution agent sessions per PR before blocking. A conflict the
    # agent cannot resolve in this many passes is not going to resolve itself.
    MAX_CONFLICT_FIX_ATTEMPTS = 3
    # Grace period after CI passes before checking reviews. Review bots (CodeRabbit) post their
    # review comments a little *after* CI completes, not as a blocking status check — so a short
    # delay would race the merge ahead of the comments. 120s gives them time to land.
    REVIEW_DELAY = 120  # seconds to wait after CI passes before checking reviews
    # Cap on the release-check failure text persisted into state and injected
    # into the release-fix prompt. Keep the tail (FAIL marker + reasoning) so
    # state.json stays small even when the check emits a long transcript.
    RELEASE_FAIL_DETAILS_MAX_CHARS = 4000

    def __init__(
        self,
        agent: AgentWrapper,
        state_manager: StateManager,
        github_client: GitHubClient,
        pr_context: PRContextManager,
        webhook_emitter: WebhookEmitter | None = None,
    ) -> None:
        """Initialize stage handler.

        Args:
            agent: The agent wrapper for running queries.
            state_manager: The state manager for persistence.
            github_client: GitHub client for PR operations.
            pr_context: PR context manager for comments/CI logs.
            webhook_emitter: Optional webhook emitter for CI events.
        """
        self.agent = agent
        self.state_manager = state_manager
        self.github_client = github_client
        self.pr_context = pr_context
        self.webhook_emitter = webhook_emitter
        # Consecutive UNKNOWN-mergeable/merge-status-error counts keyed by PR number.
        # Instance-level (not persisted) so state.py stays untouched; entries are
        # reset when the PR merges/closes or mergeability resolves.
        self._merge_unknown_attempts: dict[int, int] = {}
        # Branch-protection cache: maps base_branch → frozenset of required check names.
        # Fetched once per branch per handler lifetime; branch-protection rules don't
        # change between CI polls, so a per-wait fetch is pure N+1 waste.
        self._required_checks_cache: dict[str, set[str]] = {}
