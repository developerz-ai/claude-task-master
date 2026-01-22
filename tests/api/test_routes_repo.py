"""Tests for repository setup REST endpoints.

Tests the repo setup endpoints that support AI developer workflows:
- POST /repo/clone: Clone a git repository to the workspace
- POST /repo/setup: Set up a cloned repository for development
- POST /repo/plan: Create a plan for a repository (read-only, no work)

These endpoints enable deploying Claude Task Master to servers where it can
clone repositories, set them up for development, and plan work.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

# =============================================================================
# POST /repo/clone Tests
# =============================================================================


def test_post_clone_repo_success(api_client, temp_dir, monkeypatch):
    """Test successful repository clone via POST /repo/clone."""
    # Mock git clone subprocess
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result):
        response = api_client.post(
            "/repo/clone",
            json={
                "url": "https://github.com/test/repo.git",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "Successfully cloned" in data["message"]
    assert data["repo_url"] == "https://github.com/test/repo.git"
    assert data["target_dir"] is not None
    assert "repo" in data["target_dir"]  # Should contain repo name


def test_post_clone_repo_with_target_dir(api_client, temp_dir, monkeypatch):
    """Test clone with custom target directory."""
    target_dir = str(temp_dir / "custom" / "location")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result):
        response = api_client.post(
            "/repo/clone",
            json={
                "url": "https://github.com/test/repo.git",
                "target_dir": target_dir,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["target_dir"] == target_dir


def test_post_clone_repo_with_branch(api_client, temp_dir, monkeypatch):
    """Test clone with specific branch."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""

    def check_branch_in_command(cmd, *args, **kwargs):
        """Verify --branch flag is passed to git."""
        assert "--branch" in cmd
        assert "develop" in cmd
        return mock_result

    with patch("subprocess.run", side_effect=check_branch_in_command):
        response = api_client.post(
            "/repo/clone",
            json={
                "url": "https://github.com/test/repo.git",
                "branch": "develop",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["branch"] == "develop"


def test_post_clone_repo_empty_url(api_client):
    """Test that empty URL returns 422 (Pydantic validation)."""
    response = api_client.post(
        "/repo/clone",
        json={"url": ""},
    )

    assert response.status_code == 422  # Pydantic validation error (min_length=1)


def test_post_clone_repo_invalid_url_format(api_client):
    """Test that invalid URL format returns 400."""
    response = api_client.post(
        "/repo/clone",
        json={"url": "not-a-valid-url"},
    )

    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert "Invalid repository URL" in data["message"]


def test_post_clone_repo_git_clone_fails(api_client, temp_dir):
    """Test handling of git clone failure."""
    mock_result = MagicMock()
    mock_result.returncode = 128
    mock_result.stderr = "fatal: repository not found"

    with patch("subprocess.run", return_value=mock_result):
        response = api_client.post(
            "/repo/clone",
            json={"url": "https://github.com/test/nonexistent.git"},
        )

    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert "clone_failed" in data["error"]
    assert "repository not found" in data["detail"].lower()


def test_post_clone_repo_target_already_exists(api_client, temp_dir):
    """Test that cloning to existing directory fails."""
    # Create a directory that will conflict
    existing_dir = temp_dir / "workspace" / "claude-task-master" / "repo"
    existing_dir.mkdir(parents=True, exist_ok=True)

    # Mock the default workspace base to use temp_dir
    with patch(
        "claude_task_master.mcp.tools.DEFAULT_WORKSPACE_BASE",
        temp_dir / "workspace" / "claude-task-master",
    ):
        response = api_client.post(
            "/repo/clone",
            json={"url": "https://github.com/test/repo.git"},
        )

    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert "already exists" in data["message"]


def test_post_clone_repo_timeout(api_client, temp_dir):
    """Test handling of git clone timeout."""
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 300)):
        response = api_client.post(
            "/repo/clone",
            json={"url": "https://github.com/test/huge-repo.git"},
        )

    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert "timed out" in data["message"].lower()


def test_post_clone_repo_git_not_installed(api_client, temp_dir):
    """Test handling when git is not installed."""
    with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
        response = api_client.post(
            "/repo/clone",
            json={"url": "https://github.com/test/repo.git"},
        )

    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert "Git is not installed" in data["message"]


def test_post_clone_repo_ssh_url(api_client, temp_dir):
    """Test cloning with SSH URL format."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result):
        response = api_client.post(
            "/repo/clone",
            json={"url": "git@github.com:test/repo.git"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


def test_post_clone_repo_validation_missing_url(api_client):
    """Test that request without URL returns 422 validation error."""
    response = api_client.post(
        "/repo/clone",
        json={},
    )

    assert response.status_code == 422  # Pydantic validation error


# =============================================================================
# POST /repo/setup Tests
# =============================================================================


def test_post_setup_repo_success_python(api_client, temp_dir):
    """Test successful Python repository setup."""
    # Create a Python project structure
    repo_dir = temp_dir / "test-python-repo"
    repo_dir.mkdir(parents=True)
    (repo_dir / "pyproject.toml").write_text("[project]\nname = 'test'\n")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Success"
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result):
        with patch("shutil.which", return_value="/usr/bin/uv"):
            response = api_client.post(
                "/repo/setup",
                json={"work_dir": str(repo_dir)},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "setup completed" in data["message"].lower()
    assert data["work_dir"] == str(repo_dir)
    assert len(data["steps_completed"]) > 0


def test_post_setup_repo_success_node(api_client, temp_dir):
    """Test successful Node.js repository setup."""
    # Create a Node.js project structure
    repo_dir = temp_dir / "test-node-repo"
    repo_dir.mkdir(parents=True)
    (repo_dir / "package.json").write_text('{"name": "test"}')

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Success"
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result):
        with patch("shutil.which", return_value="/usr/bin/npm"):
            response = api_client.post(
                "/repo/setup",
                json={"work_dir": str(repo_dir)},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["dependencies_installed"] is True


def test_post_setup_repo_directory_not_found(api_client, temp_dir):
    """Test setup with non-existent directory."""
    nonexistent_dir = str(temp_dir / "does-not-exist")

    response = api_client.post(
        "/repo/setup",
        json={"work_dir": nonexistent_dir},
    )

    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "not_found"
    assert "does not exist" in data["message"].lower()


def test_post_setup_repo_path_is_file(api_client, temp_dir):
    """Test setup when path is a file not directory."""
    file_path = temp_dir / "not-a-dir.txt"
    file_path.write_text("test")

    response = api_client.post(
        "/repo/setup",
        json={"work_dir": str(file_path)},
    )

    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert "not a directory" in data["message"].lower()


def test_post_setup_repo_with_setup_scripts(api_client, temp_dir):
    """Test setup runs setup scripts if present."""
    repo_dir = temp_dir / "test-repo-with-scripts"
    repo_dir.mkdir(parents=True)
    scripts_dir = repo_dir / "scripts"
    scripts_dir.mkdir()

    # Create a setup script
    setup_script = scripts_dir / "setup-hooks.sh"
    setup_script.write_text("#!/bin/bash\necho 'Setting up hooks'")
    setup_script.chmod(0o755)

    (repo_dir / "pyproject.toml").write_text("[project]\nname = 'test'\n")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Success"
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result):
        with patch("shutil.which", return_value="/usr/bin/uv"):
            response = api_client.post(
                "/repo/setup",
                json={"work_dir": str(repo_dir)},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["setup_scripts_run"]) > 0


def test_post_setup_repo_validation_missing_work_dir(api_client):
    """Test that request without work_dir returns 422 validation error."""
    response = api_client.post(
        "/repo/setup",
        json={},
    )

    assert response.status_code == 422  # Pydantic validation error


def test_post_setup_repo_empty_work_dir(api_client):
    """Test that empty work_dir returns 422 validation error."""
    response = api_client.post(
        "/repo/setup",
        json={"work_dir": ""},
    )

    assert response.status_code == 422  # Pydantic validation error (min_length=1)


# =============================================================================
# POST /repo/plan Tests
# =============================================================================


def test_post_plan_repo_success(api_client, temp_dir):
    """Test successful repository planning."""
    # Create a repository directory
    repo_dir = temp_dir / "test-plan-repo"
    repo_dir.mkdir(parents=True)
    (repo_dir / "README.md").write_text("# Test Project")

    # Mock the plan_repo function at the routes_repo module level
    mock_plan = """## Tasks

- [ ] Task 1: Setup project structure
- [ ] Task 2: Implement core features
- [ ] Task 3: Add tests
"""
    mock_criteria = "All tests pass and code is documented"

    with patch("claude_task_master.api.routes_repo.plan_repo") as mock_plan_repo:
        mock_plan_repo.return_value = {
            "success": True,
            "message": "Plan created successfully",
            "work_dir": str(repo_dir),
            "goal": "Implement user authentication",
            "plan": mock_plan,
            "criteria": mock_criteria,
            "run_id": "test-run-id",
        }

        response = api_client.post(
            "/repo/plan",
            json={
                "work_dir": str(repo_dir),
                "goal": "Implement user authentication",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "plan created" in data["message"].lower()
    assert data["work_dir"] == str(repo_dir)
    assert data["goal"] == "Implement user authentication"
    assert data["plan"] is not None
    assert data["criteria"] is not None
    assert data["run_id"] is not None


def test_post_plan_repo_with_custom_model(api_client, temp_dir):
    """Test planning with custom model."""
    repo_dir = temp_dir / "test-plan-repo"
    repo_dir.mkdir(parents=True)

    with patch("claude_task_master.api.routes_repo.plan_repo") as mock_plan_repo:
        mock_plan_repo.return_value = {
            "success": True,
            "message": "Plan created successfully",
            "work_dir": str(repo_dir),
            "goal": "Fix bugs",
            "plan": "- [ ] Task",
            "criteria": "Criteria",
            "run_id": "test-run-id",
        }

        response = api_client.post(
            "/repo/plan",
            json={
                "work_dir": str(repo_dir),
                "goal": "Fix bugs",
                "model": "haiku",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


def test_post_plan_repo_directory_not_found(api_client, temp_dir):
    """Test planning with non-existent directory."""
    nonexistent_dir = str(temp_dir / "does-not-exist")

    response = api_client.post(
        "/repo/plan",
        json={
            "work_dir": nonexistent_dir,
            "goal": "Do something",
        },
    )

    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "not_found"


def test_post_plan_repo_validation_missing_fields(api_client):
    """Test that request without required fields returns 422 validation error."""
    # Missing work_dir
    response = api_client.post(
        "/repo/plan",
        json={"goal": "Test goal"},
    )
    assert response.status_code == 422

    # Missing goal
    response = api_client.post(
        "/repo/plan",
        json={"work_dir": "/some/path"},
    )
    assert response.status_code == 422

    # Missing both
    response = api_client.post(
        "/repo/plan",
        json={},
    )
    assert response.status_code == 422


def test_post_plan_repo_empty_goal(api_client, temp_dir):
    """Test that empty goal returns 422 validation error."""
    repo_dir = temp_dir / "test-repo"
    repo_dir.mkdir()

    response = api_client.post(
        "/repo/plan",
        json={
            "work_dir": str(repo_dir),
            "goal": "",
        },
    )

    assert response.status_code == 422  # Pydantic validation error (min_length=1)


def test_post_plan_repo_invalid_model(api_client, temp_dir):
    """Test that invalid model returns 422 validation error."""
    repo_dir = temp_dir / "test-repo"
    repo_dir.mkdir()

    response = api_client.post(
        "/repo/plan",
        json={
            "work_dir": str(repo_dir),
            "goal": "Test",
            "model": "invalid-model",
        },
    )

    assert response.status_code == 422  # Pydantic validation error (pattern mismatch)


def test_post_plan_repo_long_goal(api_client, temp_dir):
    """Test planning with a long goal description."""
    repo_dir = temp_dir / "test-repo"
    repo_dir.mkdir()

    long_goal = "A" * 5000  # 5KB goal

    with patch("claude_task_master.api.routes_repo.plan_repo") as mock_plan_repo:
        mock_plan_repo.return_value = {
            "success": True,
            "message": "Plan created successfully",
            "work_dir": str(repo_dir),
            "goal": long_goal,
            "plan": "- [ ] Task",
            "criteria": "Criteria",
            "run_id": "test-run-id",
        }

        response = api_client.post(
            "/repo/plan",
            json={
                "work_dir": str(repo_dir),
                "goal": long_goal,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


# =============================================================================
# Integration Tests
# =============================================================================


def test_repo_workflow_clone_setup_plan(api_client, temp_dir):
    """Test complete workflow: clone → setup → plan."""
    target_dir = temp_dir / "integration-test-repo"

    # Step 1: Clone
    mock_clone_result = MagicMock()
    mock_clone_result.returncode = 0
    mock_clone_result.stderr = ""

    # Mock subprocess.run to create the directory and simulate successful clone
    def mock_git_clone(cmd, *args, **kwargs):
        """Simulate git clone creating the directory."""
        if "clone" in cmd:
            # Extract target directory from command (last argument)
            target = Path(cmd[-1])
            target.mkdir(parents=True, exist_ok=True)
            (target / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        return mock_clone_result

    with patch("subprocess.run", side_effect=mock_git_clone):
        clone_response = api_client.post(
            "/repo/clone",
            json={
                "url": "https://github.com/test/repo.git",
                "target_dir": str(target_dir),
            },
        )

    assert clone_response.status_code == 200
    assert clone_response.json()["success"] is True

    # Step 2: Setup
    mock_setup_result = MagicMock()
    mock_setup_result.returncode = 0
    mock_setup_result.stdout = "Success"
    mock_setup_result.stderr = ""

    with patch("subprocess.run", return_value=mock_setup_result):
        with patch("shutil.which", return_value="/usr/bin/uv"):
            setup_response = api_client.post(
                "/repo/setup",
                json={"work_dir": str(target_dir)},
            )

    assert setup_response.status_code == 200
    assert setup_response.json()["success"] is True

    # Step 3: Plan
    with patch("claude_task_master.api.routes_repo.plan_repo") as mock_plan_repo:
        mock_plan_repo.return_value = {
            "success": True,
            "message": "Plan created successfully",
            "work_dir": str(target_dir),
            "goal": "Implement feature X",
            "plan": "- [ ] Task",
            "criteria": "Criteria",
            "run_id": "test-run-id",
        }

        plan_response = api_client.post(
            "/repo/plan",
            json={
                "work_dir": str(target_dir),
                "goal": "Implement feature X",
            },
        )

    assert plan_response.status_code == 200
    plan_data = plan_response.json()
    assert plan_data["success"] is True
    assert plan_data["plan"] is not None
    assert plan_data["run_id"] is not None


def test_repo_endpoints_independent_of_task_state(api_client, temp_dir):
    """Test that repo endpoints work without an active task."""
    # Don't create any task state files

    repo_dir = temp_dir / "independent-repo"
    repo_dir.mkdir(parents=True)
    (repo_dir / "README.md").write_text("# Test")

    # Create minimal project marker so setup detects it
    (repo_dir / "pyproject.toml").write_text("[project]\nname = 'test'\n")

    # Should be able to use setup even without task state
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Success"
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result):
        with patch("shutil.which", return_value=None):  # No uv available
            response = api_client.post(
                "/repo/setup",
                json={"work_dir": str(repo_dir)},
            )

    # Should succeed - repo operations don't require task state
    assert response.status_code == 200


# =============================================================================
# Model Validation Tests
# =============================================================================


def test_clone_repo_request_model():
    """Test CloneRepoRequest model validation."""
    from claude_task_master.api.models import CloneRepoRequest

    # Valid request with all fields
    request = CloneRepoRequest(
        url="https://github.com/test/repo.git",
        target_dir="/path/to/target",
        branch="main",
    )
    assert request.url == "https://github.com/test/repo.git"
    assert request.target_dir == "/path/to/target"
    assert request.branch == "main"

    # Valid request with minimal fields
    request = CloneRepoRequest(url="https://github.com/test/repo.git")
    assert request.url == "https://github.com/test/repo.git"
    assert request.target_dir is None
    assert request.branch is None


def test_setup_repo_request_model():
    """Test SetupRepoRequest model validation."""
    from claude_task_master.api.models import SetupRepoRequest

    request = SetupRepoRequest(work_dir="/path/to/repo")
    assert request.work_dir == "/path/to/repo"


def test_plan_repo_request_model():
    """Test PlanRepoRequest model validation."""
    from claude_task_master.api.models import PlanRepoRequest

    # Valid request with all fields
    request = PlanRepoRequest(
        work_dir="/path/to/repo",
        goal="Implement feature",
        model="sonnet",
    )
    assert request.work_dir == "/path/to/repo"
    assert request.goal == "Implement feature"
    assert request.model == "sonnet"

    # Valid request with default model
    request = PlanRepoRequest(work_dir="/path/to/repo", goal="Fix bug")
    assert request.model == "opus"  # Default


def test_clone_repo_response_model():
    """Test CloneRepoResponse model."""
    from claude_task_master.api.models import CloneRepoResponse

    response = CloneRepoResponse(
        success=True,
        message="Cloned successfully",
        repo_url="https://github.com/test/repo.git",
        target_dir="/path/to/repo",
        branch="main",
    )
    assert response.success is True
    assert response.message == "Cloned successfully"
    assert response.repo_url == "https://github.com/test/repo.git"
    assert response.target_dir == "/path/to/repo"
    assert response.branch == "main"


def test_setup_repo_response_model():
    """Test SetupRepoResponse model."""
    from claude_task_master.api.models import SetupRepoResponse

    response = SetupRepoResponse(
        success=True,
        message="Setup completed",
        work_dir="/path/to/repo",
        steps_completed=["Created venv", "Installed dependencies"],
        venv_path="/path/to/repo/.venv",
        dependencies_installed=True,
        setup_scripts_run=["scripts/setup-hooks.sh"],
    )
    assert response.success is True
    assert len(response.steps_completed) == 2
    assert response.dependencies_installed is True
    assert len(response.setup_scripts_run) == 1


def test_plan_repo_response_model():
    """Test PlanRepoResponse model."""
    from claude_task_master.api.models import PlanRepoResponse

    response = PlanRepoResponse(
        success=True,
        message="Plan created",
        work_dir="/path/to/repo",
        goal="Implement feature",
        plan="- [ ] Task 1\n- [ ] Task 2",
        criteria="All tests pass",
        run_id="run-123",
    )
    assert response.success is True
    assert response.work_dir == "/path/to/repo"
    assert response.goal == "Implement feature"
    assert response.plan is not None
    assert response.criteria == "All tests pass"
    assert response.run_id == "run-123"
