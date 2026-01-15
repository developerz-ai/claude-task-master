"""Tests for the prompts module."""

from claude_task_master.core.prompts import (
    PromptBuilder,
    PromptSection,
    build_context_extraction_prompt,
    build_error_recovery_prompt,
    build_planning_prompt,
    build_task_completion_check_prompt,
    build_verification_prompt,
    build_work_prompt,
)

# =============================================================================
# PromptSection Tests
# =============================================================================


class TestPromptSection:
    """Tests for PromptSection dataclass."""

    def test_render_basic(self) -> None:
        """Test basic section rendering."""
        section = PromptSection(
            title="Test Section",
            content="This is the content.",
        )
        result = section.render()
        assert "## Test Section" in result
        assert "This is the content." in result

    def test_render_excluded(self) -> None:
        """Test section excluded when include_if is False."""
        section = PromptSection(
            title="Hidden Section",
            content="This should not appear.",
            include_if=False,
        )
        result = section.render()
        assert result == ""

    def test_default_include(self) -> None:
        """Test section included by default."""
        section = PromptSection(
            title="Default",
            content="Content",
        )
        assert section.include_if is True


# =============================================================================
# PromptBuilder Tests
# =============================================================================


class TestPromptBuilder:
    """Tests for PromptBuilder class."""

    def test_empty_builder(self) -> None:
        """Test building with no sections."""
        builder = PromptBuilder()
        result = builder.build()
        assert result == ""

    def test_intro_only(self) -> None:
        """Test building with only intro."""
        builder = PromptBuilder(intro="Welcome to the prompt.")
        result = builder.build()
        assert result == "Welcome to the prompt."

    def test_add_section(self) -> None:
        """Test adding a section."""
        builder = PromptBuilder()
        builder.add_section("First", "First content")
        result = builder.build()
        assert "## First" in result
        assert "First content" in result

    def test_method_chaining(self) -> None:
        """Test that add_section returns self for chaining."""
        builder = PromptBuilder()
        result = builder.add_section("A", "a").add_section("B", "b")
        assert result is builder
        assert len(builder.sections) == 2

    def test_multiple_sections(self) -> None:
        """Test multiple sections."""
        builder = PromptBuilder(intro="Intro")
        builder.add_section("Section A", "Content A")
        builder.add_section("Section B", "Content B")
        result = builder.build()

        assert "Intro" in result
        assert "## Section A" in result
        assert "## Section B" in result
        assert result.index("Section A") < result.index("Section B")

    def test_conditional_sections(self) -> None:
        """Test conditional section inclusion."""
        builder = PromptBuilder()
        builder.add_section("Included", "yes", include_if=True)
        builder.add_section("Excluded", "no", include_if=False)
        result = builder.build()

        assert "Included" in result
        assert "Excluded" not in result


# =============================================================================
# Planning Prompt Tests
# =============================================================================


class TestBuildPlanningPrompt:
    """Tests for build_planning_prompt function."""

    def test_basic_prompt(self) -> None:
        """Test basic planning prompt generation."""
        prompt = build_planning_prompt("Build a todo app")

        assert "Build a todo app" in prompt
        assert "Phase 1: Explore" in prompt
        assert "Phase 2: Create Plan" in prompt
        assert "Success Criteria" in prompt

    def test_with_context(self) -> None:
        """Test planning prompt with context."""
        prompt = build_planning_prompt(
            goal="Add feature X",
            context="Previously discovered: uses React",
        )

        assert "Add feature X" in prompt
        assert "Previously discovered: uses React" in prompt
        assert "Previous Context" in prompt

    def test_includes_task_format(self) -> None:
        """Test that task format is included."""
        prompt = build_planning_prompt("Any goal")

        assert "[coding]" in prompt
        assert "[quick]" in prompt
        assert "[general]" in prompt

    def test_includes_pr_strategy(self) -> None:
        """Test PR strategy section exists."""
        prompt = build_planning_prompt("Any goal")

        assert "PR Strategy" in prompt
        assert "gh pr create" in prompt or "Create PR" in prompt

    def test_includes_gitignore_reminder(self) -> None:
        """Test gitignore reminder is included."""
        prompt = build_planning_prompt("Any goal")

        assert ".claude-task-master/" in prompt
        assert ".gitignore" in prompt


# =============================================================================
# Work Prompt Tests
# =============================================================================


class TestBuildWorkPrompt:
    """Tests for build_work_prompt function."""

    def test_basic_prompt(self) -> None:
        """Test basic work prompt generation."""
        prompt = build_work_prompt("Implement user login")

        assert "Implement user login" in prompt
        assert "Current Task" in prompt
        assert "Execution" in prompt

    def test_with_context(self) -> None:
        """Test work prompt with context."""
        prompt = build_work_prompt(
            task_description="Add logout button",
            context="Uses JWT authentication",
        )

        assert "Add logout button" in prompt
        assert "Uses JWT authentication" in prompt
        assert "Context" in prompt

    def test_with_pr_comments(self) -> None:
        """Test work prompt with PR comments."""
        prompt = build_work_prompt(
            task_description="Fix bug",
            pr_comments="Please add error handling",
        )

        assert "Fix bug" in prompt
        assert "Please add error handling" in prompt
        assert "PR Review Feedback" in prompt

    def test_with_file_hints(self) -> None:
        """Test work prompt with file hints."""
        prompt = build_work_prompt(
            task_description="Refactor auth",
            file_hints=["src/auth.py", "tests/test_auth.py"],
        )

        assert "Refactor auth" in prompt
        assert "src/auth.py" in prompt
        assert "tests/test_auth.py" in prompt
        assert "Relevant Files" in prompt

    def test_file_hints_limited(self) -> None:
        """Test that file hints are limited to 10."""
        files = [f"file{i}.py" for i in range(20)]
        prompt = build_work_prompt(
            task_description="Task",
            file_hints=files,
        )

        # Should include first 10
        assert "file0.py" in prompt
        assert "file9.py" in prompt
        # Should not include 11th+
        assert "file10.py" not in prompt

    def test_includes_completion_section(self) -> None:
        """Test that completion reporting section exists."""
        prompt = build_work_prompt("Any task")

        assert "On Completion" in prompt
        assert "What was completed" in prompt

    def test_includes_git_commands(self) -> None:
        """Test that git commands are included."""
        prompt = build_work_prompt("Any task")

        assert "git add" in prompt
        assert "git commit" in prompt


# =============================================================================
# Verification Prompt Tests
# =============================================================================


class TestBuildVerificationPrompt:
    """Tests for build_verification_prompt function."""

    def test_basic_prompt(self) -> None:
        """Test basic verification prompt."""
        prompt = build_verification_prompt(
            criteria="All tests pass\nCI is green",
        )

        assert "All tests pass" in prompt
        assert "CI is green" in prompt
        assert "Success Criteria" in prompt

    def test_with_tasks_summary(self) -> None:
        """Test verification with tasks summary."""
        prompt = build_verification_prompt(
            criteria="Tests pass",
            tasks_summary="Implemented login\nAdded tests",
        )

        assert "Tests pass" in prompt
        assert "Implemented login" in prompt
        assert "Completed Tasks" in prompt

    def test_includes_verification_steps(self) -> None:
        """Test verification steps are included."""
        prompt = build_verification_prompt("Any criteria")

        assert "Verification Steps" in prompt
        assert "Run tests" in prompt

    def test_includes_report_format(self) -> None:
        """Test report format guidance is included."""
        prompt = build_verification_prompt("Any criteria")

        assert "PASSED" in prompt
        assert "FAILED" in prompt


# =============================================================================
# Task Completion Check Tests
# =============================================================================


class TestBuildTaskCompletionCheckPrompt:
    """Tests for build_task_completion_check_prompt function."""

    def test_basic_prompt(self) -> None:
        """Test basic completion check prompt."""
        prompt = build_task_completion_check_prompt(
            task_description="Add feature X",
            session_output="Feature X implemented and tested.",
        )

        assert "Add feature X" in prompt
        assert "Feature X implemented and tested." in prompt
        assert "COMPLETED" in prompt
        assert "IN_PROGRESS" in prompt

    def test_includes_all_statuses(self) -> None:
        """Test all status options are included."""
        prompt = build_task_completion_check_prompt(
            task_description="Task",
            session_output="Output",
        )

        assert "COMPLETED" in prompt
        assert "IN_PROGRESS" in prompt
        assert "BLOCKED" in prompt
        assert "FAILED" in prompt


# =============================================================================
# Context Extraction Tests
# =============================================================================


class TestBuildContextExtractionPrompt:
    """Tests for build_context_extraction_prompt function."""

    def test_basic_prompt(self) -> None:
        """Test basic context extraction prompt."""
        prompt = build_context_extraction_prompt(
            session_output="Discovered the app uses Flask.",
        )

        assert "Discovered the app uses Flask." in prompt
        assert "Extract" in prompt

    def test_with_existing_context(self) -> None:
        """Test extraction with existing context."""
        prompt = build_context_extraction_prompt(
            session_output="Found new pattern",
            existing_context="Previously: uses Redis",
        )

        assert "Found new pattern" in prompt
        assert "Previously: uses Redis" in prompt
        assert "Existing Context" in prompt

    def test_includes_extraction_categories(self) -> None:
        """Test extraction categories are included."""
        prompt = build_context_extraction_prompt("Output")

        assert "Patterns" in prompt
        assert "Decisions" in prompt
        assert "Issues" in prompt

    def test_output_truncated(self) -> None:
        """Test that very long output is truncated."""
        long_output = "x" * 10000
        prompt = build_context_extraction_prompt(long_output)

        # Should be truncated to 5000 chars
        assert len(prompt) < len(long_output)


# =============================================================================
# Error Recovery Tests
# =============================================================================


class TestBuildErrorRecoveryPrompt:
    """Tests for build_error_recovery_prompt function."""

    def test_basic_prompt(self) -> None:
        """Test basic error recovery prompt."""
        prompt = build_error_recovery_prompt(
            error_message="ModuleNotFoundError: flask",
        )

        assert "ModuleNotFoundError: flask" in prompt
        assert "Error" in prompt
        assert "Recovery Steps" in prompt

    def test_with_task_context(self) -> None:
        """Test error recovery with task context."""
        prompt = build_error_recovery_prompt(
            error_message="Test failed",
            task_context="Running unit tests for auth module",
        )

        assert "Test failed" in prompt
        assert "Running unit tests for auth module" in prompt
        assert "Task Context" in prompt

    def test_with_attempted_actions(self) -> None:
        """Test error recovery with attempted actions."""
        prompt = build_error_recovery_prompt(
            error_message="Connection refused",
            attempted_actions=[
                "Restarted server",
                "Checked port availability",
            ],
        )

        assert "Connection refused" in prompt
        assert "Restarted server" in prompt
        assert "Checked port availability" in prompt
        assert "Already Tried" in prompt

    def test_includes_recovery_steps(self) -> None:
        """Test recovery steps are included."""
        prompt = build_error_recovery_prompt("Error")

        assert "Analyze the error" in prompt
        assert "Implement fix" in prompt
        assert "Verify" in prompt
