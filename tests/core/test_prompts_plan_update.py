"""Tests for the plan update prompts."""

from claude_task_master.core.prompts_plan_update import build_plan_update_prompt


class TestBuildPlanUpdatePrompt:
    """Tests for the build_plan_update_prompt function."""

    def test_basic_prompt_structure(self):
        """Test that the prompt has the basic required structure."""
        current_plan = "## Task List\n- [ ] Task 1"
        change_request = "Add a new feature"

        prompt = build_plan_update_prompt(current_plan, change_request)

        # Check required sections exist
        assert "Plan update mode" in prompt
        assert change_request in prompt
        assert "Current Plan" in prompt
        assert "Rules" in prompt

    def test_includes_current_plan(self):
        """Test that the current plan is included in the prompt."""
        current_plan = "## Task List\n- [x] Completed task\n- [ ] Pending task"
        change_request = "Modify the plan"

        prompt = build_plan_update_prompt(current_plan, change_request)

        assert "Completed task" in prompt
        assert "Pending task" in prompt
        assert "[x]" in prompt
        assert "[ ]" in prompt

    def test_includes_change_request(self):
        """Test that the change request is prominently included."""
        current_plan = "## Task List\n- [ ] Task 1"
        change_request = "Add authentication to the API endpoints"

        prompt = build_plan_update_prompt(current_plan, change_request)

        assert "Add authentication to the API endpoints" in prompt
        assert "Change request:" in prompt or "change request" in prompt.lower()

    def test_includes_goal_when_provided(self):
        """Test that the goal is included when provided."""
        current_plan = "## Task List\n- [ ] Task 1"
        change_request = "Update plan"
        goal = "Build a complete REST API"

        prompt = build_plan_update_prompt(current_plan, change_request, goal=goal)

        assert "Original Goal" in prompt
        assert "Build a complete REST API" in prompt

    def test_excludes_goal_when_not_provided(self):
        """Test that goal section is not present when goal is None."""
        current_plan = "## Task List\n- [ ] Task 1"
        change_request = "Update plan"

        prompt = build_plan_update_prompt(current_plan, change_request, goal=None)

        assert "Original Goal" not in prompt

    def test_includes_context_when_provided(self):
        """Test that context is included when provided."""
        current_plan = "## Task List\n- [ ] Task 1"
        change_request = "Update plan"
        context = "Session 1: Explored the codebase and found key files."

        prompt = build_plan_update_prompt(current_plan, change_request, context=context)

        assert "Previous Context" in prompt
        assert "Explored the codebase" in prompt

    def test_excludes_context_when_not_provided(self):
        """Test that context section is not present when context is None."""
        current_plan = "## Task List\n- [ ] Task 1"
        change_request = "Update plan"

        prompt = build_plan_update_prompt(current_plan, change_request, context=None)

        assert "Previous Context" not in prompt

    def test_includes_tool_instructions(self):
        """Test that tool instructions are present."""
        current_plan = "## Task List\n- [ ] Task 1"
        change_request = "Update plan"

        prompt = build_plan_update_prompt(current_plan, change_request)

        # Should mention tools available and no writing
        assert "All tools available" in prompt
        assert "Do NOT write files" in prompt

    def test_preserves_completed_tasks_instruction(self):
        """Test that the prompt instructs to preserve completed tasks."""
        current_plan = "## Task List\n- [x] Done task\n- [ ] Pending task"
        change_request = "Update plan"

        prompt = build_plan_update_prompt(current_plan, change_request)

        assert "completed" in prompt.lower()
        assert "preserve" in prompt.lower() or "keep" in prompt.lower()
        assert "[x]" in prompt

    def test_includes_plan_update_complete_marker(self):
        """Test that the prompt mentions PLAN UPDATE COMPLETE marker."""
        current_plan = "## Task List\n- [ ] Task 1"
        change_request = "Update plan"

        prompt = build_plan_update_prompt(current_plan, change_request)

        assert "PLAN UPDATE COMPLETE" in prompt

    def test_full_prompt_with_all_parameters(self):
        """Test prompt generation with all parameters provided."""
        current_plan = """## Task List

### PR 1: Infrastructure
- [x] `[quick]` Setup project
- [ ] `[coding]` Add database models

### PR 2: API
- [ ] `[coding]` Add API endpoints

## Success Criteria
1. All tests pass
"""
        change_request = "Add authentication and rate limiting to the API"
        goal = "Build a secure REST API"
        context = "Session 1: Set up project structure."

        prompt = build_plan_update_prompt(
            current_plan=current_plan,
            change_request=change_request,
            goal=goal,
            context=context,
        )

        # Check all sections are present
        assert "Plan update mode" in prompt
        assert "Add authentication and rate limiting" in prompt
        assert "Build a secure REST API" in prompt
        assert "Set up project structure" in prompt
        assert "Infrastructure" in prompt
        assert "API endpoints" in prompt
        assert "Success Criteria" in prompt


class TestPlanUpdatePromptFormat:
    """Tests for the format requirements of the plan update prompt."""

    def test_markdown_format_instructions(self):
        """Test that the prompt includes markdown format instructions."""
        current_plan = "## Task List\n- [ ] Task 1"
        change_request = "Update plan"

        prompt = build_plan_update_prompt(current_plan, change_request)

        # Should mention markdown checkbox format
        assert "[ ]" in prompt or "checkbox" in prompt.lower()
        assert "Task List" in prompt

    def test_complexity_tags_mentioned(self):
        """Test that complexity tags are mentioned for task formatting."""
        current_plan = "## Task List\n- [ ] Task 1"
        change_request = "Update plan"

        prompt = build_plan_update_prompt(current_plan, change_request)

        # Should mention keeping complexity tags in rules
        assert "complexity tags" in prompt.lower()

    def test_pr_structure_mentioned(self):
        """Test that PR structure is mentioned."""
        current_plan = "## Task List\n- [ ] Task 1"
        change_request = "Update plan"

        prompt = build_plan_update_prompt(current_plan, change_request)

        # Should mention PR grouping
        assert "PR" in prompt
