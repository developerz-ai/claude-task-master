"""Integration test fixtures for end-to-end workflow testing.

This module provides comprehensive fixtures for testing the full claude-task-master
workflow with mocked Claude Agent SDK. The fixtures simulate realistic scenarios
including planning phases, work sessions, error handling, and state transitions.
"""

import json
from collections.abc import AsyncGenerator, Generator
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =============================================================================
# Mock Claude Agent SDK Module
# =============================================================================


class MockClaudeAgentSDK:
    """Mock implementation of the Claude Agent SDK.

    This provides a realistic mock that can be configured to return different
    responses based on test scenarios. It supports both successful operations
    and simulated failures for testing error handling.
    """

    def __init__(self):
        """Initialize the mock SDK."""
        self._planning_responses: list[str] = []
        self._work_responses: list[str] = []
        self._verify_responses: list[str] = []
        self._response_index = 0
        self._should_fail = False
        self._fail_after = None
        self._failure_type = None
        self.query_calls: list[dict] = []

    def set_planning_response(self, response: str) -> None:
        """Set a planning phase response."""
        self._planning_responses.append(response)

    def set_work_response(self, response: str) -> None:
        """Set a work session response."""
        self._work_responses.append(response)

    def set_verify_response(self, response: str) -> None:
        """Set a verification phase response."""
        self._verify_responses.append(response)

    def configure_failure(
        self, fail_after: int | None = None, failure_type: str = "generic"
    ) -> None:
        """Configure the mock to fail after a certain number of calls.

        Args:
            fail_after: Number of successful calls before failing. None means don't fail.
            failure_type: Type of failure - 'generic', 'rate_limit', 'auth', 'timeout', 'connection'
        """
        self._fail_after = fail_after
        self._failure_type = failure_type
        self._should_fail = fail_after is not None

    def reset(self) -> None:
        """Reset the mock state."""
        self._planning_responses = []
        self._work_responses = []
        self._verify_responses = []
        self._response_index = 0
        self._should_fail = False
        self._fail_after = None
        self._failure_type = None
        self.query_calls = []

    def _get_next_response(self, phase: str) -> str:
        """Get the next response for a given phase."""
        if phase == "planning":
            responses = self._planning_responses
        elif phase == "work":
            responses = self._work_responses
        else:
            responses = self._verify_responses

        if not responses:
            return self._get_default_response(phase)

        # Cycle through responses if we have multiple
        idx = min(self._response_index, len(responses) - 1)
        return responses[idx]

    def _get_default_response(self, phase: str) -> str:
        """Get default response for a phase."""
        if phase == "planning":
            return """## Task List

- [ ] Set up project structure
- [ ] Implement core feature
- [ ] Add unit tests
- [ ] Write documentation

## Success Criteria

1. All tests pass with >80% coverage
2. Documentation is complete
3. No critical bugs"""
        elif phase == "work":
            return "Task completed successfully. Made the required changes and verified they work."
        else:
            return "All success criteria have been met. All tests pass."

    def _maybe_raise_error(self) -> None:
        """Raise an error if configured to fail."""
        if not self._should_fail:
            return

        self._response_index += 1
        if self._fail_after is not None and self._response_index > self._fail_after:
            error_map = {
                "generic": Exception("Generic SDK error"),
                "rate_limit": Exception("Rate limit exceeded - too many requests"),
                "auth": Exception("Authentication failed - 401 unauthorized"),
                "timeout": Exception("Request timeout after 30 seconds"),
                "connection": Exception("Connection error - network unavailable"),
            }
            error_type = self._failure_type or "generic"
            raise error_map.get(error_type, Exception("Unknown error"))

    @property
    def ClaudeAgentOptions(self):
        """Mock ClaudeAgentOptions class."""
        return MagicMock

    async def query(self, prompt: str, options: Any = None) -> AsyncGenerator[AsyncMock, None]:
        """Mock async query function.

        This simulates the SDK's query method which yields messages.
        """
        self.query_calls.append({"prompt": prompt, "options": options})
        self._maybe_raise_error()

        # Determine phase from prompt
        if "planning" in prompt.lower() or "create" in prompt.lower():
            phase = "planning"
        elif "verify" in prompt.lower() or "criteria" in prompt.lower():
            phase = "verify"
        else:
            phase = "work"

        response = self._get_next_response(phase)

        # Yield mock message objects to simulate streaming
        mock_text_block = MagicMock()
        mock_text_block.text = response
        type(mock_text_block).__name__ = "TextBlock"

        mock_message = MagicMock()
        mock_message.content = [mock_text_block]
        type(mock_message).__name__ = "AssistantMessage"

        yield mock_message

        # Yield result message
        mock_result = MagicMock()
        mock_result.result = response
        type(mock_result).__name__ = "ResultMessage"

        yield mock_result

        self._response_index += 1


# =============================================================================
# Integration Test Fixtures
# =============================================================================


@pytest.fixture
def mock_sdk() -> Generator[MockClaudeAgentSDK, None, None]:
    """Provide a configurable mock Claude Agent SDK."""
    sdk = MockClaudeAgentSDK()
    yield sdk
    sdk.reset()


@pytest.fixture
def integration_temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory for integration tests."""
    with TemporaryDirectory(prefix="claude_task_master_integration_") as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def integration_state_dir(integration_temp_dir: Path) -> Path:
    """Provide a state directory for integration tests."""
    state_dir = integration_temp_dir / ".claude-task-master"
    state_dir.mkdir(parents=True)
    return state_dir


@pytest.fixture
def integration_logs_dir(integration_state_dir: Path) -> Path:
    """Provide a logs directory for integration tests."""
    logs_dir = integration_state_dir / "logs"
    logs_dir.mkdir(parents=True)
    return logs_dir


@pytest.fixture
def mock_credentials_data() -> dict[str, Any]:
    """Provide mock credentials for integration tests."""
    future_timestamp = int((datetime.now() + timedelta(hours=1)).timestamp() * 1000)
    return {
        "claudeAiOauth": {
            "accessToken": "integration-test-token-12345",
            "refreshToken": "integration-test-refresh-67890",
            "expiresAt": future_timestamp,
            "tokenType": "Bearer",
        }
    }


@pytest.fixture
def mock_credentials_file(
    integration_temp_dir: Path, mock_credentials_data: dict[str, Any]
) -> Path:
    """Create a mock credentials file for integration tests."""
    claude_dir = integration_temp_dir / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    credentials_path = claude_dir / ".credentials.json"
    credentials_path.write_text(json.dumps(mock_credentials_data))
    return credentials_path


@pytest.fixture
def patched_sdk(mock_sdk: MockClaudeAgentSDK):
    """Patch the Claude Agent SDK import."""
    # Create a mock module that matches the SDK structure
    mock_module = MagicMock()
    mock_module.query = mock_sdk.query
    mock_module.ClaudeAgentOptions = mock_sdk.ClaudeAgentOptions

    with patch.dict("sys.modules", {"claude_agent_sdk": mock_module}):
        yield mock_sdk


@pytest.fixture
def integration_workflow_setup(
    integration_temp_dir: Path,
    integration_state_dir: Path,
    mock_credentials_file: Path,
    patched_sdk: MockClaudeAgentSDK,
    monkeypatch,
):
    """Set up complete integration test environment.

    This fixture provides a fully configured environment with:
    - Mocked Claude Agent SDK
    - Temporary state directory
    - Mock credentials
    - Working directory set to temp directory

    Returns a dict with all the configured components.
    """
    from claude_task_master.core.credentials import CredentialManager
    from claude_task_master.core.state import StateManager

    # Set up environment
    original_cwd = Path.cwd()
    monkeypatch.chdir(integration_temp_dir)

    # Patch StateManager to use our temp directory
    monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

    # Patch CredentialManager to use our mock credentials path
    monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

    yield {
        "temp_dir": integration_temp_dir,
        "state_dir": integration_state_dir,
        "credentials_file": mock_credentials_file,
        "sdk": patched_sdk,
        "original_cwd": original_cwd,
    }


# =============================================================================
# Pre-configured State Fixtures
# =============================================================================


@pytest.fixture
def sample_plan_content() -> str:
    """Provide sample plan content for testing."""
    return """## Task List

- [ ] Initialize project structure
- [ ] Implement authentication module
- [ ] Add user registration endpoint
- [ ] Create login endpoint
- [ ] Add unit tests for auth
- [ ] Write API documentation

## Success Criteria

1. All authentication endpoints respond with correct status codes
2. User registration creates valid user records
3. Login returns valid JWT tokens
4. All tests pass with >90% coverage
5. API documentation is complete and accurate
"""


@pytest.fixture
def sample_goal() -> str:
    """Provide a sample goal for testing."""
    return "Implement user authentication system with registration and login"


@pytest.fixture
def pre_planned_state(
    integration_state_dir: Path,
    sample_plan_content: str,
    sample_goal: str,
) -> dict[str, Any]:
    """Create a pre-planned state for testing resume functionality.

    This creates a state where planning is complete and work should begin.
    """
    timestamp = datetime.now().isoformat()
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    state_data = {
        "status": "working",
        "current_task_index": 0,
        "session_count": 1,
        "current_pr": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_id": run_id,
        "model": "sonnet",
        "options": {
            "auto_merge": True,
            "max_sessions": None,
            "pause_on_pr": False,
        },
    }

    # Write state file
    state_file = integration_state_dir / "state.json"
    state_file.write_text(json.dumps(state_data, indent=2))

    # Write goal file
    goal_file = integration_state_dir / "goal.txt"
    goal_file.write_text(sample_goal)

    # Write plan file
    plan_file = integration_state_dir / "plan.md"
    plan_file.write_text(sample_plan_content)

    # Create logs directory
    logs_dir = integration_state_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    return {
        "state_file": state_file,
        "goal_file": goal_file,
        "plan_file": plan_file,
        "run_id": run_id,
        "state_data": state_data,
    }


@pytest.fixture
def paused_state(
    integration_state_dir: Path,
    sample_plan_content: str,
    sample_goal: str,
) -> dict[str, Any]:
    """Create a paused state for testing resume functionality."""
    timestamp = datetime.now().isoformat()
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    # Mark first two tasks as complete in the plan
    plan_with_progress = sample_plan_content.replace(
        "- [ ] Initialize project structure", "- [x] Initialize project structure"
    ).replace("- [ ] Implement authentication module", "- [x] Implement authentication module")

    state_data = {
        "status": "paused",
        "current_task_index": 2,
        "session_count": 3,
        "current_pr": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_id": run_id,
        "model": "sonnet",
        "options": {
            "auto_merge": True,
            "max_sessions": 10,
            "pause_on_pr": False,
        },
    }

    # Write state file
    state_file = integration_state_dir / "state.json"
    state_file.write_text(json.dumps(state_data, indent=2))

    # Write goal file
    goal_file = integration_state_dir / "goal.txt"
    goal_file.write_text(sample_goal)

    # Write plan file with progress
    plan_file = integration_state_dir / "plan.md"
    plan_file.write_text(plan_with_progress)

    # Write progress file
    progress_file = integration_state_dir / "progress.md"
    progress_file.write_text("""# Progress Tracker

**Session:** 3
**Current Task:** 3 of 6

## Task List

✓ [x] **Task 1:** Initialize project structure
✓ [x] **Task 2:** Implement authentication module
→ [ ] **Task 3:** Add user registration endpoint
  [ ] **Task 4:** Create login endpoint
  [ ] **Task 5:** Add unit tests for auth
  [ ] **Task 6:** Write API documentation
""")

    # Write context file
    context_file = integration_state_dir / "context.md"
    context_file.write_text("""# Accumulated Context

## Session 1
Set up basic project structure with authentication module skeleton.

## Session 2
Implemented authentication module with JWT support.

## Key Learnings
- Using bcrypt for password hashing
- JWT tokens with 24h expiry
""")

    # Create logs directory
    logs_dir = integration_state_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    return {
        "state_file": state_file,
        "goal_file": goal_file,
        "plan_file": plan_file,
        "progress_file": progress_file,
        "context_file": context_file,
        "run_id": run_id,
        "state_data": state_data,
    }


@pytest.fixture
def blocked_state(
    integration_state_dir: Path,
    sample_plan_content: str,
    sample_goal: str,
) -> dict[str, Any]:
    """Create a blocked state for testing error recovery."""
    timestamp = datetime.now().isoformat()
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    state_data = {
        "status": "blocked",
        "current_task_index": 1,
        "session_count": 2,
        "current_pr": 42,
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_id": run_id,
        "model": "sonnet",
        "options": {
            "auto_merge": True,
            "max_sessions": None,
            "pause_on_pr": False,
        },
    }

    # Write state file
    state_file = integration_state_dir / "state.json"
    state_file.write_text(json.dumps(state_data, indent=2))

    # Write goal file
    goal_file = integration_state_dir / "goal.txt"
    goal_file.write_text(sample_goal)

    # Write plan file with first task complete
    plan_with_progress = sample_plan_content.replace(
        "- [ ] Initialize project structure", "- [x] Initialize project structure"
    )
    plan_file = integration_state_dir / "plan.md"
    plan_file.write_text(plan_with_progress)

    # Create logs directory
    logs_dir = integration_state_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    return {
        "state_file": state_file,
        "goal_file": goal_file,
        "plan_file": plan_file,
        "run_id": run_id,
        "state_data": state_data,
    }


@pytest.fixture
def completed_state(
    integration_state_dir: Path,
    sample_plan_content: str,
    sample_goal: str,
) -> dict[str, Any]:
    """Create a completed/success state for testing terminal states."""
    timestamp = datetime.now().isoformat()
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    state_data = {
        "status": "success",
        "current_task_index": 6,
        "session_count": 6,
        "current_pr": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_id": run_id,
        "model": "sonnet",
        "options": {
            "auto_merge": True,
            "max_sessions": None,
            "pause_on_pr": False,
        },
    }

    # Mark all tasks complete
    completed_plan = sample_plan_content.replace("- [ ]", "- [x]")

    # Write state file
    state_file = integration_state_dir / "state.json"
    state_file.write_text(json.dumps(state_data, indent=2))

    # Write goal file
    goal_file = integration_state_dir / "goal.txt"
    goal_file.write_text(sample_goal)

    # Write plan file
    plan_file = integration_state_dir / "plan.md"
    plan_file.write_text(completed_plan)

    # Create logs directory
    logs_dir = integration_state_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    return {
        "state_file": state_file,
        "goal_file": goal_file,
        "plan_file": plan_file,
        "run_id": run_id,
        "state_data": state_data,
    }


@pytest.fixture
def failed_state(
    integration_state_dir: Path,
    sample_plan_content: str,
    sample_goal: str,
) -> dict[str, Any]:
    """Create a failed state for testing terminal states."""
    timestamp = datetime.now().isoformat()
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    state_data = {
        "status": "failed",
        "current_task_index": 2,
        "session_count": 5,
        "current_pr": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_id": run_id,
        "model": "sonnet",
        "options": {
            "auto_merge": True,
            "max_sessions": 5,
            "pause_on_pr": False,
        },
    }

    # Write state file
    state_file = integration_state_dir / "state.json"
    state_file.write_text(json.dumps(state_data, indent=2))

    # Write goal file
    goal_file = integration_state_dir / "goal.txt"
    goal_file.write_text(sample_goal)

    # Write plan file
    plan_file = integration_state_dir / "plan.md"
    plan_file.write_text(sample_plan_content)

    # Create logs directory
    logs_dir = integration_state_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    return {
        "state_file": state_file,
        "goal_file": goal_file,
        "plan_file": plan_file,
        "run_id": run_id,
        "state_data": state_data,
    }


# =============================================================================
# Helper Fixtures for Testing Scenarios
# =============================================================================


@pytest.fixture
def planning_response_simple() -> str:
    """Simple planning response with few tasks."""
    return """## Task List

- [ ] Task one: Initialize project
- [ ] Task two: Add feature
- [ ] Task three: Write tests

## Success Criteria

1. All tests pass
2. Feature is working
"""


@pytest.fixture
def planning_response_complex() -> str:
    """Complex planning response with many tasks."""
    return """## Task List

- [ ] Phase 1: Project Setup
  - [ ] Initialize repository structure
  - [ ] Configure build system
  - [ ] Set up CI/CD pipeline
- [ ] Phase 2: Core Implementation
  - [ ] Implement database models
  - [ ] Create API endpoints
  - [ ] Add authentication
- [ ] Phase 3: Testing & Documentation
  - [ ] Write unit tests
  - [ ] Write integration tests
  - [ ] Create API documentation
  - [ ] Write user guide

## Success Criteria

1. All tests pass with >90% coverage
2. API documentation is complete
3. User guide covers all features
4. CI/CD pipeline runs successfully
5. No security vulnerabilities
"""


@pytest.fixture
def work_response_success() -> str:
    """Successful work session response."""
    return """Task completed successfully!

## Summary
- Implemented the required feature
- Added necessary tests
- Updated documentation

## Changes Made
- Created new file: src/feature.py
- Modified: src/main.py
- Added tests: tests/test_feature.py

## Tests Run
All 15 tests passed.

## Git Commit
Committed changes with message: "feat: Add new feature"
"""


@pytest.fixture
def work_response_with_issues() -> str:
    """Work session response with blockers."""
    return """Task partially completed.

## Summary
Encountered issues during implementation.

## Issues Found
1. Missing dependency: package-xyz
2. Configuration file not found

## Attempted Solutions
- Tried alternative approach but hit same issue
- Need manual intervention to resolve

## Recommendation
Please install package-xyz and re-run.
"""


@pytest.fixture
def verify_response_success() -> str:
    """Successful verification response."""
    return """All success criteria have been met!

## Criteria Verification

1. ✓ All tests pass with >80% coverage - VERIFIED (92% coverage)
2. ✓ Documentation is complete - VERIFIED
3. ✓ No critical bugs - VERIFIED

Overall Status: SUCCESS
"""


@pytest.fixture
def verify_response_failure() -> str:
    """Failed verification response."""
    return """Some success criteria have NOT been met.

## Criteria Verification

1. ✓ All tests pass with >80% coverage - VERIFIED (85% coverage)
2. ✗ Documentation is complete - NOT MET (missing API docs)
3. ✓ No critical bugs - VERIFIED

Overall Status: FAILED

## Recommendation
Please complete the API documentation before marking as successful.
"""


@pytest.fixture
def mock_github_client():
    """Provide a mocked GitHubClient for integration tests."""
    mock = MagicMock()
    mock.create_pr = MagicMock(return_value=123)
    mock.get_pr_status = MagicMock(
        return_value=MagicMock(
            number=123,
            ci_state="SUCCESS",
            unresolved_threads=0,
            total_threads=0,
            resolved_threads=0,
            check_details=[],
            mergeable=True,
            merged=False,
        )
    )
    mock.get_pr_comments = MagicMock(return_value="")
    mock.merge_pr = MagicMock()
    mock.get_pr_for_current_branch = MagicMock(return_value=None)
    mock.wait_for_ci = MagicMock(return_value=("SUCCESS", None))
    return mock


@pytest.fixture(autouse=True)
def patch_github_client_globally(mock_github_client):
    """Globally patch GitHubClient for all integration tests.

    This prevents any test from calling the real `gh` CLI which can hang.
    We need to patch multiple locations since GitHubClient is imported in various ways:
    - claude_task_master.github.GitHubClient (re-exported from __init__.py)
    - claude_task_master.github.client.GitHubClient (original definition)
    """
    with (
        patch(
            "claude_task_master.github.GitHubClient",
            return_value=mock_github_client,
        ),
        patch(
            "claude_task_master.github.client.GitHubClient",
            return_value=mock_github_client,
        ),
    ):
        yield


@pytest.fixture
def mock_agent_wrapper(mock_sdk: MockClaudeAgentSDK):
    """Provide a mock AgentWrapper for integration tests."""
    mock = MagicMock()
    mock.run_planning_phase = MagicMock(
        return_value={
            "plan": "## Task List\n- [ ] Task 1\n\n## Success Criteria\n1. Done",
            "criteria": "1. Done",
            "raw_output": "Plan created successfully",
        }
    )
    mock.run_work_session = MagicMock(
        return_value={
            "output": "Task completed successfully",
            "success": True,
        }
    )
    mock.verify_success_criteria = MagicMock(
        return_value={
            "success": True,
            "details": "All criteria met!",
        }
    )
    return mock


# =============================================================================
# Key Listener Mock (Auto-use)
# =============================================================================


@pytest.fixture(autouse=True)
def mock_key_listener():
    """Automatically mock the key listener to prevent blocking in tests.

    The key listener uses select() on stdin which blocks in test environments.
    This fixture mocks the key listener functions to be no-ops.

    We need to patch both the original module AND the imported names in orchestrator
    since the imports happen at module load time.
    """
    with (
        # Patch the original module functions
        patch("claude_task_master.core.key_listener.start_listening"),
        patch("claude_task_master.core.key_listener.stop_listening"),
        patch("claude_task_master.core.key_listener.check_escape", return_value=False),
        patch(
            "claude_task_master.core.key_listener.is_cancellation_requested",
            return_value=False,
        ),
        patch(
            "claude_task_master.core.key_listener.get_cancellation_reason",
            return_value=None,
        ),
        # Patch the imported names in orchestrator
        patch("claude_task_master.core.orchestrator.start_listening"),
        patch("claude_task_master.core.orchestrator.stop_listening"),
        patch(
            "claude_task_master.core.orchestrator.is_cancellation_requested",
            return_value=False,
        ),
        patch("claude_task_master.core.orchestrator.reset_escape"),
    ):
        yield
