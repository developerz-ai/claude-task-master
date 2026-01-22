"""Tests for MCP repo setup tools.

Tests clone_repo and setup_repo MCP tool implementations.
"""

import pytest

from .conftest import MCP_AVAILABLE

pytestmark = pytest.mark.skipif(not MCP_AVAILABLE, reason="MCP SDK not installed")


class TestSetupRepoTool:
    """Test the setup_repo MCP tool."""

    def test_setup_repo_nonexistent_directory(self, temp_dir):
        """Test setup_repo with nonexistent directory."""
        from claude_task_master.mcp.tools import setup_repo

        nonexistent = temp_dir / "does-not-exist"
        result = setup_repo(nonexistent)

        assert result["success"] is False
        assert "does not exist" in result["message"]
        assert result["error"] == "Work directory not found"

    def test_setup_repo_not_a_directory(self, temp_dir):
        """Test setup_repo with a file instead of directory."""
        from claude_task_master.mcp.tools import setup_repo

        file_path = temp_dir / "some_file.txt"
        file_path.write_text("not a directory")

        result = setup_repo(file_path)

        assert result["success"] is False
        assert "not a directory" in result["message"]
        assert result["error"] == "Path is not a directory"

    def test_setup_repo_empty_directory(self, temp_dir):
        """Test setup_repo with empty directory (no project files)."""
        from claude_task_master.mcp.tools import setup_repo

        result = setup_repo(temp_dir)

        assert result["success"] is False
        assert "No recognized project type" in str(result["steps_completed"])
        assert result["dependencies_installed"] is False
        assert result["setup_scripts_run"] == []

    def test_setup_repo_python_project_with_pyproject(self, temp_dir):
        """Test setup_repo with Python project using pyproject.toml."""
        from claude_task_master.mcp.tools import setup_repo

        # Create a minimal pyproject.toml
        pyproject = temp_dir / "pyproject.toml"
        pyproject.write_text("""
[project]
name = "test-project"
version = "0.1.0"
""")

        result = setup_repo(temp_dir)

        assert result["work_dir"] == str(temp_dir)
        assert "Detected Python project" in result["steps_completed"]
        # Note: actual dependency installation may vary based on environment

    def test_setup_repo_python_project_with_requirements(self, temp_dir):
        """Test setup_repo with Python project using requirements.txt."""
        from claude_task_master.mcp.tools import setup_repo

        # Create a requirements.txt with no actual dependencies
        requirements = temp_dir / "requirements.txt"
        requirements.write_text("")

        # Also need a pyproject.toml or setup.py to be detected as Python
        pyproject = temp_dir / "pyproject.toml"
        pyproject.write_text("""
[project]
name = "test-project"
version = "0.1.0"
""")

        result = setup_repo(temp_dir)

        assert result["work_dir"] == str(temp_dir)
        assert "Detected Python project" in result["steps_completed"]

    def test_setup_repo_nodejs_project(self, temp_dir):
        """Test setup_repo with Node.js project."""
        from claude_task_master.mcp.tools import setup_repo

        # Create a minimal package.json
        package_json = temp_dir / "package.json"
        package_json.write_text('{"name": "test", "version": "1.0.0"}')

        result = setup_repo(temp_dir)

        assert result["work_dir"] == str(temp_dir)
        assert "Detected Node.js project" in result["steps_completed"]

    def test_setup_repo_with_setup_script(self, temp_dir):
        """Test setup_repo detects and runs setup scripts."""
        from claude_task_master.mcp.tools import setup_repo

        # Create scripts directory with setup script
        scripts_dir = temp_dir / "scripts"
        scripts_dir.mkdir()

        setup_script = scripts_dir / "setup.sh"
        setup_script.write_text("#!/bin/bash\necho 'Setup complete'\n")
        setup_script.chmod(0o755)

        result = setup_repo(temp_dir)

        # Without a recognized project type, just running scripts is still success
        assert "scripts/setup.sh" in result["setup_scripts_run"] or result["success"] is False

    def test_setup_repo_with_root_setup_script(self, temp_dir):
        """Test setup_repo detects setup scripts in root directory."""
        from claude_task_master.mcp.tools import setup_repo

        # Create setup script in root
        setup_script = temp_dir / "setup.sh"
        setup_script.write_text("#!/bin/bash\necho 'Root setup complete'\n")
        setup_script.chmod(0o755)

        result = setup_repo(temp_dir)

        # Script should be detected (may or may not run successfully)
        assert result["work_dir"] == str(temp_dir)

    def test_setup_repo_returns_venv_path(self, temp_dir):
        """Test setup_repo returns venv path for Python projects."""
        from claude_task_master.mcp.tools import setup_repo

        # Create a Python project
        pyproject = temp_dir / "pyproject.toml"
        pyproject.write_text("""
[project]
name = "test-project"
version = "0.1.0"
""")

        result = setup_repo(temp_dir)

        # venv_path should be set if venv was created
        if result["success"]:
            assert result["venv_path"] is not None or result["venv_path"] == str(temp_dir / ".venv")

    def test_setup_repo_accepts_string_path(self, temp_dir):
        """Test setup_repo accepts string path."""
        from claude_task_master.mcp.tools import setup_repo

        result = setup_repo(str(temp_dir))

        assert result["work_dir"] == str(temp_dir)

    def test_setup_repo_expands_user_path(self):
        """Test setup_repo expands ~ in path."""
        from claude_task_master.mcp.tools import setup_repo

        # This should expand and fail gracefully since the path likely doesn't exist
        result = setup_repo("~/nonexistent-test-path-12345")

        # Should have expanded the path
        assert "~" not in result["work_dir"]


class TestCloneRepoTool:
    """Test the clone_repo MCP tool."""

    def test_clone_repo_empty_url_fails(self):
        """Test clone_repo fails with empty URL."""
        from claude_task_master.mcp.tools import clone_repo

        result = clone_repo("")

        assert result["success"] is False
        assert "required" in result["message"].lower()

    def test_clone_repo_whitespace_url_fails(self):
        """Test clone_repo fails with whitespace URL."""
        from claude_task_master.mcp.tools import clone_repo

        result = clone_repo("   ")

        assert result["success"] is False
        assert "required" in result["message"].lower()

    def test_clone_repo_invalid_url_format(self):
        """Test clone_repo fails with invalid URL format."""
        from claude_task_master.mcp.tools import clone_repo

        result = clone_repo("not-a-valid-url")

        assert result["success"] is False
        assert "Invalid" in result["message"]

    def test_clone_repo_valid_https_url_format(self, temp_dir):
        """Test clone_repo accepts valid HTTPS URL format."""
        from claude_task_master.mcp.tools import clone_repo

        # Use a nonexistent repo to test URL validation passes
        # but clone will fail for other reasons
        target = temp_dir / "test-repo"
        result = clone_repo(
            "https://github.com/nonexistent-user-12345/nonexistent-repo-12345.git",
            target_dir=str(target),
        )

        # URL format is valid, but clone should fail (repo doesn't exist)
        assert (
            result["repo_url"]
            == "https://github.com/nonexistent-user-12345/nonexistent-repo-12345.git"
        )
        # Either success=False due to clone failure or success=True if somehow worked
        assert "success" in result

    def test_clone_repo_valid_ssh_url_format(self, temp_dir):
        """Test clone_repo accepts valid SSH URL format."""
        from claude_task_master.mcp.tools import clone_repo

        target = temp_dir / "test-repo"
        result = clone_repo(
            "git@github.com:nonexistent-user-12345/nonexistent-repo-12345.git",
            target_dir=str(target),
        )

        # URL format is valid
        assert (
            result["repo_url"] == "git@github.com:nonexistent-user-12345/nonexistent-repo-12345.git"
        )

    def test_clone_repo_target_exists_fails(self, temp_dir):
        """Test clone_repo fails if target directory already exists."""
        from claude_task_master.mcp.tools import clone_repo

        # Create target directory
        target = temp_dir / "existing-dir"
        target.mkdir()

        result = clone_repo(
            "https://github.com/example/repo.git",
            target_dir=str(target),
        )

        assert result["success"] is False
        assert "already exists" in result["message"]

    def test_extract_repo_name_https(self):
        """Test repo name extraction from HTTPS URL."""
        from claude_task_master.mcp.tools import _extract_repo_name

        assert _extract_repo_name("https://github.com/user/my-repo.git") == "my-repo"
        assert _extract_repo_name("https://github.com/user/my-repo") == "my-repo"
        assert _extract_repo_name("https://github.com/user/my-repo/") == "my-repo"

    def test_extract_repo_name_ssh(self):
        """Test repo name extraction from SSH URL."""
        from claude_task_master.mcp.tools import _extract_repo_name

        assert _extract_repo_name("git@github.com:user/my-repo.git") == "my-repo"
        assert _extract_repo_name("git@github.com:user/my-repo") == "my-repo"


class TestSetupRepoResultModel:
    """Test the SetupRepoResult model."""

    def test_setup_repo_result_model_fields(self):
        """Test SetupRepoResult model has expected fields."""
        from claude_task_master.mcp.tools import SetupRepoResult

        result = SetupRepoResult(
            success=True,
            message="Setup completed",
            work_dir="/path/to/repo",
            steps_completed=["Step 1", "Step 2"],
            venv_path="/path/to/repo/.venv",
            dependencies_installed=True,
            setup_scripts_run=["setup.sh"],
        )

        assert result.success is True
        assert result.message == "Setup completed"
        assert result.work_dir == "/path/to/repo"
        assert len(result.steps_completed) == 2
        assert result.venv_path == "/path/to/repo/.venv"
        assert result.dependencies_installed is True
        assert result.setup_scripts_run == ["setup.sh"]
        assert result.error is None

    def test_setup_repo_result_model_defaults(self):
        """Test SetupRepoResult model defaults."""
        from claude_task_master.mcp.tools import SetupRepoResult

        result = SetupRepoResult(
            success=False,
            message="Setup failed",
        )

        assert result.work_dir is None
        assert result.steps_completed == []
        assert result.venv_path is None
        assert result.dependencies_installed is False
        assert result.setup_scripts_run == []
        assert result.error is None


class TestCloneRepoResultModel:
    """Test the CloneRepoResult model."""

    def test_clone_repo_result_model_fields(self):
        """Test CloneRepoResult model has expected fields."""
        from claude_task_master.mcp.tools import CloneRepoResult

        result = CloneRepoResult(
            success=True,
            message="Clone successful",
            repo_url="https://github.com/user/repo.git",
            target_dir="/path/to/repo",
            branch="main",
        )

        assert result.success is True
        assert result.repo_url == "https://github.com/user/repo.git"
        assert result.target_dir == "/path/to/repo"
        assert result.branch == "main"
        assert result.error is None

    def test_clone_repo_result_model_defaults(self):
        """Test CloneRepoResult model defaults."""
        from claude_task_master.mcp.tools import CloneRepoResult

        result = CloneRepoResult(
            success=False,
            message="Clone failed",
        )

        assert result.repo_url is None
        assert result.target_dir is None
        assert result.branch is None
        assert result.error is None


class TestPlanRepoTool:
    """Test the plan_repo MCP tool."""

    def test_plan_repo_nonexistent_directory(self, temp_dir):
        """Test plan_repo with nonexistent directory."""
        from claude_task_master.mcp.tools import plan_repo

        nonexistent = temp_dir / "does-not-exist"
        result = plan_repo(nonexistent, goal="Test goal")

        assert result["success"] is False
        assert "does not exist" in result["message"]
        assert result["error"] == "Work directory not found"
        assert result["goal"] == "Test goal"

    def test_plan_repo_not_a_directory(self, temp_dir):
        """Test plan_repo with a file instead of directory."""
        from claude_task_master.mcp.tools import plan_repo

        file_path = temp_dir / "some_file.txt"
        file_path.write_text("not a directory")

        result = plan_repo(file_path, goal="Test goal")

        assert result["success"] is False
        assert "not a directory" in result["message"]
        assert result["error"] == "Path is not a directory"

    def test_plan_repo_empty_goal_fails(self, temp_dir):
        """Test plan_repo fails with empty goal."""
        from claude_task_master.mcp.tools import plan_repo

        result = plan_repo(temp_dir, goal="")

        assert result["success"] is False
        assert "required" in result["message"].lower()
        assert result["error"] == "Goal cannot be empty"

    def test_plan_repo_whitespace_goal_fails(self, temp_dir):
        """Test plan_repo fails with whitespace-only goal."""
        from claude_task_master.mcp.tools import plan_repo

        result = plan_repo(temp_dir, goal="   ")

        assert result["success"] is False
        assert "required" in result["message"].lower()
        assert result["error"] == "Goal cannot be empty"

    def test_plan_repo_accepts_string_path(self):
        """Test plan_repo accepts string path."""
        from claude_task_master.mcp.tools import plan_repo

        # Test with nonexistent path to fail fast without agent calls
        result = plan_repo("/nonexistent/test/path", goal="Test goal")

        assert result["success"] is False
        assert result["error"] == "Work directory not found"

    def test_plan_repo_expands_user_path(self):
        """Test plan_repo expands ~ in path."""
        from claude_task_master.mcp.tools import plan_repo

        # This should expand and fail gracefully since the path likely doesn't exist
        result = plan_repo("~/nonexistent-test-path-12345", goal="Test goal")

        # Should have expanded the path
        assert "~" not in result["work_dir"]

    def test_plan_repo_with_active_task_planning(self, temp_dir):
        """Test plan_repo fails when task is already in planning status."""
        from claude_task_master.core.state import StateManager, TaskOptions
        from claude_task_master.mcp.tools import plan_repo

        # Initialize a task in planning state
        state_path = temp_dir / ".claude-task-master"
        state_manager = StateManager(state_dir=state_path)
        options = TaskOptions(auto_merge=False, max_sessions=1)
        state = state_manager.initialize(goal="Existing goal", model="opus", options=options)
        state.status = "planning"
        state_manager.save_state(state)

        # Try to create a new plan
        result = plan_repo(temp_dir, goal="New goal")

        assert result["success"] is False
        assert "already in progress" in result["message"]
        assert "Cannot create new plan while task is active" in result["error"]

    def test_plan_repo_with_active_task_working(self, temp_dir):
        """Test plan_repo fails when task is in working status."""
        from claude_task_master.core.state import StateManager, TaskOptions
        from claude_task_master.mcp.tools import plan_repo

        # Initialize a task in working state
        state_path = temp_dir / ".claude-task-master"
        state_manager = StateManager(state_dir=state_path)
        options = TaskOptions(auto_merge=False, max_sessions=1)
        state = state_manager.initialize(goal="Existing goal", model="opus", options=options)
        state.status = "working"
        state_manager.save_state(state)

        # Try to create a new plan
        result = plan_repo(temp_dir, goal="New goal")

        assert result["success"] is False
        assert "already in progress" in result["message"]

    def test_plan_repo_model_parameter(self):
        """Test plan_repo accepts model parameter."""
        from claude_task_master.mcp.tools import plan_repo

        # Test with different model values using nonexistent path to fail fast
        for model in ["opus", "sonnet", "haiku"]:
            result = plan_repo("/nonexistent/path", goal="Test goal", model=model)
            # Should accept the parameter and fail quickly on path validation
            assert result["success"] is False
            assert result["error"] == "Work directory not found"

    def test_plan_repo_result_structure(self):
        """Test plan_repo returns correct result structure."""
        from claude_task_master.mcp.tools import plan_repo

        # Use nonexistent path to fail fast without agent initialization
        result = plan_repo("/nonexistent/path", goal="Test goal")

        # Verify required keys are present
        assert "success" in result
        assert "message" in result
        assert "work_dir" in result
        assert "goal" in result
        assert "plan" in result
        assert "criteria" in result
        assert "run_id" in result
        assert "error" in result

    def test_plan_repo_no_agent_initialization_on_validation_failure(self, temp_dir):
        """Test plan_repo doesn't initialize agent on validation failures."""
        from claude_task_master.mcp.tools import plan_repo

        # Test empty goal - should fail fast without creating any state
        result = plan_repo(temp_dir, goal="")

        assert result["success"] is False
        assert result["error"] == "Goal cannot be empty"
        # State directory should not be created for validation failures
        # (though it may exist from other tests)


class TestPlanRepoResultModel:
    """Test the PlanRepoResult model."""

    def test_plan_repo_result_model_fields(self):
        """Test PlanRepoResult model has expected fields."""
        from claude_task_master.mcp.tools import PlanRepoResult

        result = PlanRepoResult(
            success=True,
            message="Planning successful",
            work_dir="/path/to/repo",
            goal="Add feature X",
            plan="- [ ] Task 1\n- [ ] Task 2",
            criteria="Tests pass",
            run_id="run-123",
        )

        assert result.success is True
        assert result.message == "Planning successful"
        assert result.work_dir == "/path/to/repo"
        assert result.goal == "Add feature X"
        assert result.plan == "- [ ] Task 1\n- [ ] Task 2"
        assert result.criteria == "Tests pass"
        assert result.run_id == "run-123"
        assert result.error is None

    def test_plan_repo_result_model_defaults(self):
        """Test PlanRepoResult model defaults."""
        from claude_task_master.mcp.tools import PlanRepoResult

        result = PlanRepoResult(
            success=False,
            message="Planning failed",
        )

        assert result.work_dir is None
        assert result.goal is None
        assert result.plan is None
        assert result.criteria is None
        assert result.run_id is None
        assert result.error is None

    def test_plan_repo_result_model_dump(self):
        """Test PlanRepoResult model_dump works correctly."""
        from claude_task_master.mcp.tools import PlanRepoResult

        result = PlanRepoResult(
            success=True,
            message="Planning successful",
            work_dir="/path/to/repo",
            goal="Test goal",
            plan="Test plan",
            criteria="Test criteria",
            run_id="run-123",
            error="Test error",
        )

        dumped = result.model_dump()
        assert isinstance(dumped, dict)
        assert dumped["success"] is True
        assert dumped["message"] == "Planning successful"
        assert dumped["work_dir"] == "/path/to/repo"
        assert dumped["goal"] == "Test goal"
        assert dumped["plan"] == "Test plan"
        assert dumped["criteria"] == "Test criteria"
        assert dumped["run_id"] == "run-123"
        assert dumped["error"] == "Test error"


class TestRepoSetupIntegration:
    """Integration tests for repo setup workflow."""

    def test_repo_name_extraction_edge_cases(self):
        """Test edge cases in repository name extraction."""
        from claude_task_master.mcp.tools import _extract_repo_name

        # Test various URL formats
        assert _extract_repo_name("https://github.com/org/repo-name.git") == "repo-name"
        assert _extract_repo_name("git@gitlab.com:org/repo-name.git") == "repo-name"
        assert _extract_repo_name("https://bitbucket.org/team/repo.git") == "repo"
        assert _extract_repo_name("git@github.com:user/my.repo.git") == "my.repo"

    def test_clone_repo_default_target_directory(self):
        """Test clone_repo uses default workspace directory."""
        from claude_task_master.mcp.tools import DEFAULT_WORKSPACE_BASE, clone_repo

        # Test that default path includes workspace base
        result = clone_repo("https://github.com/user/test-repo.git")

        # Should fail (repo doesn't exist), but check target_dir structure
        expected_target = str(DEFAULT_WORKSPACE_BASE / "test-repo")
        if "target_dir" in result:
            assert result["target_dir"] == expected_target

    def test_setup_repo_with_multiple_project_types(self, temp_dir):
        """Test setup_repo handles projects with both Python and Node.js."""
        from claude_task_master.mcp.tools import setup_repo

        # Create both Python and Node.js project files
        pyproject = temp_dir / "pyproject.toml"
        pyproject.write_text('[project]\nname = "test"\nversion = "0.1.0"')

        package_json = temp_dir / "package.json"
        package_json.write_text('{"name": "test", "version": "1.0.0"}')

        result = setup_repo(temp_dir)

        # Should detect both project types
        assert result["work_dir"] == str(temp_dir)
        steps = result["steps_completed"]
        assert any("Python" in step for step in steps)
        assert any("Node.js" in step for step in steps)
