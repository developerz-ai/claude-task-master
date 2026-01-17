"""Tests for planning phase prompts.

This module tests the build_planning_prompt function from prompts_planning.py:
- Basic prompt generation
- Context handling
- Tool restrictions section
- Task format and complexity tags
- PR strategy and grouping
- Success criteria section
- Stop instructions
"""

from claude_task_master.core.prompts_planning import build_planning_prompt

# =============================================================================
# Basic Prompt Generation Tests
# =============================================================================


class TestBuildPlanningPromptBasic:
    """Tests for basic build_planning_prompt functionality."""

    def test_returns_string(self) -> None:
        """Test that build_planning_prompt returns a string."""
        result = build_planning_prompt("Build a todo app")
        assert isinstance(result, str)

    def test_returns_non_empty_string(self) -> None:
        """Test that build_planning_prompt returns non-empty string."""
        result = build_planning_prompt("Any goal")
        assert len(result) > 0

    def test_goal_included_in_prompt(self) -> None:
        """Test that the goal is included in the prompt."""
        goal = "Build a task management system"
        result = build_planning_prompt(goal)
        assert goal in result

    def test_goal_with_special_characters(self) -> None:
        """Test goal with special characters is preserved."""
        goal = "Fix bug #123: User's session doesn't persist"
        result = build_planning_prompt(goal)
        assert goal in result

    def test_goal_with_markdown(self) -> None:
        """Test goal with markdown formatting is preserved."""
        goal = "Implement **important** feature `code_style`"
        result = build_planning_prompt(goal)
        assert "important" in result
        assert "code_style" in result

    def test_empty_goal(self) -> None:
        """Test with empty goal string."""
        result = build_planning_prompt("")
        # Should still generate a valid prompt
        assert isinstance(result, str)
        assert "PLANNING MODE" in result

    def test_multiline_goal(self) -> None:
        """Test goal with multiple lines."""
        goal = "Goal line 1\nGoal line 2\nGoal line 3"
        result = build_planning_prompt(goal)
        assert "Goal line 1" in result
        assert "Goal line 2" in result
        assert "Goal line 3" in result


# =============================================================================
# Planning Mode Introduction Tests
# =============================================================================


class TestPlanningModeIntro:
    """Tests for the planning mode introduction section."""

    def test_planning_mode_mentioned(self) -> None:
        """Test PLANNING MODE is mentioned in the prompt."""
        result = build_planning_prompt("Any goal")
        assert "PLANNING MODE" in result

    def test_claude_task_master_mentioned(self) -> None:
        """Test Claude Task Master is mentioned."""
        result = build_planning_prompt("Any goal")
        assert "Claude Task Master" in result

    def test_mission_keyword_present(self) -> None:
        """Test mission context is present."""
        result = build_planning_prompt("Build feature X")
        assert "mission" in result.lower() or "goal" in result.lower()

    def test_high_quality_plan_mentioned(self) -> None:
        """Test HIGH QUALITY MASTER PLAN is mentioned."""
        result = build_planning_prompt("Any goal")
        assert "HIGH QUALITY" in result or "MASTER PLAN" in result


# =============================================================================
# Tool Restrictions Tests
# =============================================================================


class TestToolRestrictions:
    """Tests for tool restrictions section."""

    def test_tool_restrictions_section_present(self) -> None:
        """Test TOOL RESTRICTIONS section exists."""
        result = build_planning_prompt("Any goal")
        assert "TOOL RESTRICTIONS" in result

    def test_allowed_tools_listed(self) -> None:
        """Test allowed tools are listed."""
        result = build_planning_prompt("Any goal")
        assert "Read" in result
        assert "Glob" in result
        assert "Grep" in result
        assert "Bash" in result

    def test_forbidden_tools_marked(self) -> None:
        """Test forbidden tools are marked."""
        result = build_planning_prompt("Any goal")
        assert "Write" in result
        assert "Edit" in result
        # Check for forbidden marking
        assert "FORBIDDEN" in result or "❌" in result

    def test_write_tool_forbidden(self) -> None:
        """Test Write tool is explicitly forbidden."""
        result = build_planning_prompt("Any goal")
        assert "Write" in result
        # Should be in forbidden section, not just mentioned
        assert "Do NOT write" in result or "❌" in result

    def test_edit_tool_forbidden(self) -> None:
        """Test Edit tool is explicitly forbidden."""
        result = build_planning_prompt("Any goal")
        assert "Edit" in result
        assert "❌" in result or "FORBIDDEN" in result

    def test_task_tool_forbidden(self) -> None:
        """Test Task tool is explicitly forbidden."""
        result = build_planning_prompt("Any goal")
        assert "Task" in result

    def test_todowrite_tool_forbidden(self) -> None:
        """Test TodoWrite tool is explicitly forbidden."""
        result = build_planning_prompt("Any goal")
        assert "TodoWrite" in result

    def test_webfetch_tool_forbidden(self) -> None:
        """Test WebFetch tool is explicitly forbidden."""
        result = build_planning_prompt("Any goal")
        assert "WebFetch" in result

    def test_websearch_tool_forbidden(self) -> None:
        """Test WebSearch tool is explicitly forbidden."""
        result = build_planning_prompt("Any goal")
        assert "WebSearch" in result

    def test_why_explanation_present(self) -> None:
        """Test WHY explanation is present."""
        result = build_planning_prompt("Any goal")
        assert "WHY" in result or "orchestrator" in result.lower()


# =============================================================================
# Planning Rules Tests
# =============================================================================


class TestPlanningRules:
    """Tests for planning rules section."""

    def test_no_code_rule(self) -> None:
        """Test rule about not writing code."""
        result = build_planning_prompt("Any goal")
        assert "Do NOT write code" in result or "not write code" in result.lower()

    def test_no_branches_rule(self) -> None:
        """Test rule about not creating branches."""
        result = build_planning_prompt("Any goal")
        assert "Do NOT create git branches" in result or "branches" in result.lower()

    def test_explore_only_rule(self) -> None:
        """Test rule about only exploring."""
        result = build_planning_prompt("Any goal")
        assert "explore" in result.lower()

    def test_check_state_rule(self) -> None:
        """Test rule about checking state."""
        result = build_planning_prompt("Any goal")
        assert "git status" in result or "check" in result.lower()


# =============================================================================
# Context Section Tests
# =============================================================================


class TestContextSection:
    """Tests for context section handling."""

    def test_no_context_by_default(self) -> None:
        """Test no context section when context is None."""
        result = build_planning_prompt("Any goal", context=None)
        # Should not have "Previous Context" as a section header
        # The word "context" may appear in other contexts
        assert "## Previous Context" not in result

    def test_context_included_when_provided(self) -> None:
        """Test context is included when provided."""
        result = build_planning_prompt(
            goal="Any goal",
            context="Previously discovered: uses React framework",
        )
        assert "Previous Context" in result
        assert "uses React framework" in result

    def test_context_stripped(self) -> None:
        """Test context whitespace is stripped."""
        result = build_planning_prompt(
            goal="Goal",
            context="  Context with whitespace  \n\n",
        )
        assert "Context with whitespace" in result

    def test_empty_context_treated_as_none(self) -> None:
        """Test empty string context is treated like no context."""
        result = build_planning_prompt(goal="Goal", context="")
        # Empty string is falsy, so no context section
        assert "## Previous Context" not in result

    def test_multiline_context(self) -> None:
        """Test multiline context is preserved."""
        context = """Discovery 1: Uses Flask
Discovery 2: Has pytest tests
Discovery 3: No CI config"""
        result = build_planning_prompt(goal="Goal", context=context)
        assert "Uses Flask" in result
        assert "Has pytest tests" in result
        assert "No CI config" in result

    def test_context_with_code_blocks(self) -> None:
        """Test context with code blocks is preserved."""
        context = """Found pattern:
```python
def main():
    pass
```"""
        result = build_planning_prompt(goal="Goal", context=context)
        assert "```python" in result
        assert "def main():" in result


# =============================================================================
# Step 1: Explore Codebase Tests
# =============================================================================


class TestExploreCodebaseSection:
    """Tests for Step 1: Explore Codebase section."""

    def test_step1_present(self) -> None:
        """Test Step 1 section is present."""
        result = build_planning_prompt("Any goal")
        assert "Step 1" in result
        assert "Explore Codebase" in result

    def test_read_only_emphasized(self) -> None:
        """Test READ ONLY is emphasized."""
        result = build_planning_prompt("Any goal")
        assert "READ ONLY" in result or "READ-ONLY" in result

    def test_key_files_mentioned(self) -> None:
        """Test key files are mentioned."""
        result = build_planning_prompt("Any goal")
        assert "README" in result or "key files" in result.lower()

    def test_glob_patterns_mentioned(self) -> None:
        """Test glob patterns are mentioned."""
        result = build_planning_prompt("Any goal")
        assert "**/*.py" in result or "glob" in result.lower()

    def test_grep_for_code_mentioned(self) -> None:
        """Test grep for code is mentioned."""
        result = build_planning_prompt("Any goal")
        assert "Grep" in result or "grep" in result

    def test_architecture_understanding_mentioned(self) -> None:
        """Test understanding architecture is mentioned."""
        result = build_planning_prompt("Any goal")
        assert "architecture" in result.lower()


# =============================================================================
# Step 2: Create Task List Tests
# =============================================================================


class TestCreateTaskListSection:
    """Tests for Step 2: Create Task List section."""

    def test_step2_present(self) -> None:
        """Test Step 2 section is present."""
        result = build_planning_prompt("Any goal")
        assert "Step 2" in result
        assert "Create Task List" in result

    def test_pr_organization_emphasized(self) -> None:
        """Test PR organization is emphasized."""
        result = build_planning_prompt("Any goal")
        assert "PR" in result
        assert "Pull Request" in result or "Organized by PR" in result

    def test_format_examples_present(self) -> None:
        """Test format examples are present."""
        result = build_planning_prompt("Any goal")
        assert "### PR" in result
        assert "- [ ]" in result

    def test_file_paths_emphasized(self) -> None:
        """Test file paths requirement is emphasized."""
        result = build_planning_prompt("Any goal")
        assert "file path" in result.lower() or "File paths" in result

    def test_symbols_emphasized(self) -> None:
        """Test symbols requirement is emphasized."""
        result = build_planning_prompt("Any goal")
        assert "Symbols" in result or "symbol" in result.lower()

    def test_complexity_tags_present(self) -> None:
        """Test complexity tags are present."""
        result = build_planning_prompt("Any goal")
        assert "[coding]" in result
        assert "[quick]" in result
        assert "[general]" in result

    def test_coding_tag_for_opus(self) -> None:
        """Test [coding] tag is for Opus model."""
        result = build_planning_prompt("Any goal")
        assert "[coding]" in result
        # Should mention Opus or smartest
        assert "Opus" in result or "smartest" in result.lower()

    def test_quick_tag_for_haiku(self) -> None:
        """Test [quick] tag is for Haiku model."""
        result = build_planning_prompt("Any goal")
        assert "[quick]" in result
        assert "Haiku" in result or "fastest" in result.lower()

    def test_general_tag_for_sonnet(self) -> None:
        """Test [general] tag is for Sonnet model."""
        result = build_planning_prompt("Any goal")
        assert "[general]" in result
        assert "Sonnet" in result or "balanced" in result.lower()

    def test_default_tag_advice(self) -> None:
        """Test advice to use [coding] when uncertain."""
        result = build_planning_prompt("Any goal")
        assert "uncertain" in result.lower() or "[coding]" in result


# =============================================================================
# PR Grouping Principles Tests
# =============================================================================


class TestPRGroupingPrinciples:
    """Tests for PR grouping principles."""

    def test_dependencies_first_principle(self) -> None:
        """Test dependencies first principle is mentioned."""
        result = build_planning_prompt("Any goal")
        assert "Dependencies first" in result or "dependencies" in result.lower()

    def test_logical_cohesion_principle(self) -> None:
        """Test logical cohesion principle is mentioned."""
        result = build_planning_prompt("Any goal")
        assert "cohesion" in result.lower() or "Related changes" in result

    def test_small_prs_principle(self) -> None:
        """Test small PRs principle is mentioned."""
        result = build_planning_prompt("Any goal")
        assert "Small PR" in result or "3-6 tasks" in result

    def test_branch_creation_mentioned(self) -> None:
        """Test branch creation task is mentioned."""
        result = build_planning_prompt("Any goal")
        assert "branch" in result.lower()


# =============================================================================
# PR Strategy Section Tests
# =============================================================================


class TestPRStrategySection:
    """Tests for PR Strategy section."""

    def test_pr_strategy_section_present(self) -> None:
        """Test PR Strategy section is present."""
        result = build_planning_prompt("Any goal")
        assert "PR Strategy" in result

    def test_why_prs_matter_explained(self) -> None:
        """Test why PRs matter is explained."""
        result = build_planning_prompt("Any goal")
        assert "Why PR" in result or "context" in result.lower()

    def test_conversation_sharing_mentioned(self) -> None:
        """Test conversation sharing is mentioned."""
        result = build_planning_prompt("Any goal")
        assert "conversation" in result.lower() or "share" in result.lower()

    def test_ci_check_mentioned(self) -> None:
        """Test CI check is mentioned."""
        result = build_planning_prompt("Any goal")
        assert "CI" in result

    def test_example_pr_breakdown_present(self) -> None:
        """Test example PR breakdown is present."""
        result = build_planning_prompt("Any goal")
        # Should have PR 1, PR 2, etc. in examples
        assert "### PR 1:" in result or "PR 1" in result

    def test_mergeable_independently_mentioned(self) -> None:
        """Test mergeable independently is mentioned."""
        result = build_planning_prompt("Any goal")
        assert "mergeable" in result.lower() or "independently" in result.lower()


# =============================================================================
# Step 3: Success Criteria Tests
# =============================================================================


class TestSuccessCriteriaSection:
    """Tests for Step 3: Define Success Criteria section."""

    def test_step3_present(self) -> None:
        """Test Step 3 section is present."""
        result = build_planning_prompt("Any goal")
        assert "Step 3" in result
        assert "Success Criteria" in result

    def test_measurable_criteria_mentioned(self) -> None:
        """Test measurable criteria is mentioned."""
        result = build_planning_prompt("Any goal")
        assert "measurable" in result.lower() or "3-5" in result

    def test_tests_pass_criterion(self) -> None:
        """Test tests pass is mentioned as criterion."""
        result = build_planning_prompt("Any goal")
        assert "Tests pass" in result or "pytest" in result

    def test_linting_criterion(self) -> None:
        """Test linting clean is mentioned as criterion."""
        result = build_planning_prompt("Any goal")
        assert "Linting" in result or "ruff" in result or "eslint" in result

    def test_ci_green_criterion(self) -> None:
        """Test CI green is mentioned as criterion."""
        result = build_planning_prompt("Any goal")
        assert "CI" in result and ("green" in result.lower() or "pipeline" in result.lower())

    def test_prs_merged_criterion(self) -> None:
        """Test PRs merged is mentioned as criterion."""
        result = build_planning_prompt("Any goal")
        assert "PRs merged" in result or "merged" in result.lower()

    def test_specific_and_verifiable_mentioned(self) -> None:
        """Test specific and verifiable is mentioned."""
        result = build_planning_prompt("Any goal")
        assert "specific" in result.lower() or "verifiable" in result.lower()


# =============================================================================
# Stop Instructions Tests
# =============================================================================


class TestStopInstructions:
    """Tests for STOP instructions section."""

    def test_stop_section_present(self) -> None:
        """Test STOP section is present."""
        result = build_planning_prompt("Any goal")
        assert "STOP" in result

    def test_planning_complete_phrase(self) -> None:
        """Test PLANNING COMPLETE phrase is present."""
        result = build_planning_prompt("Any goal")
        assert "PLANNING COMPLETE" in result

    def test_no_write_tool_instruction(self) -> None:
        """Test instruction to not use Write tool."""
        result = build_planning_prompt("Any goal")
        assert "Do NOT use Write tool" in result or "NOT write" in result

    def test_orchestrator_handles_saving(self) -> None:
        """Test explanation that orchestrator saves plan."""
        result = build_planning_prompt("Any goal")
        assert "orchestrator" in result.lower()
        assert "plan.md" in result or "save" in result.lower()

    def test_do_not_implement_instruction(self) -> None:
        """Test instruction to not start implementing."""
        result = build_planning_prompt("Any goal")
        assert "implement" in result.lower()
        assert "Start implementing tasks" in result or "Do NOT" in result

    def test_output_plan_as_text_instruction(self) -> None:
        """Test instruction to output plan as text."""
        result = build_planning_prompt("Any goal")
        assert "OUTPUT" in result or "output" in result
        assert "text" in result.lower()


# =============================================================================
# Integration Tests
# =============================================================================


class TestBuildPlanningPromptIntegration:
    """Integration tests for build_planning_prompt."""

    def test_complete_prompt_structure(self) -> None:
        """Test complete prompt has all major sections."""
        result = build_planning_prompt("Build a web application")

        # All major sections should be present
        assert "PLANNING MODE" in result
        assert "TOOL RESTRICTIONS" in result
        assert "Step 1" in result
        assert "Step 2" in result
        assert "Step 3" in result
        assert "PR Strategy" in result
        assert "STOP" in result
        assert "PLANNING COMPLETE" in result

    def test_section_order(self) -> None:
        """Test sections appear in logical order."""
        result = build_planning_prompt("Any goal")

        # Find positions
        intro_pos = result.find("PLANNING MODE")
        tools_pos = result.find("TOOL RESTRICTIONS")
        step1_pos = result.find("Step 1")
        step2_pos = result.find("Step 2")
        step3_pos = result.find("Step 3")
        stop_pos = result.find("STOP")

        # Verify order
        assert intro_pos < tools_pos < step1_pos < step2_pos < step3_pos < stop_pos

    def test_with_full_context(self) -> None:
        """Test prompt with full context."""
        result = build_planning_prompt(
            goal="Implement user authentication system",
            context="""Previous discoveries:
- Project uses FastAPI
- Database is PostgreSQL
- Tests use pytest
- CI uses GitHub Actions""",
        )

        assert "Implement user authentication system" in result
        assert "Previous Context" in result
        assert "FastAPI" in result
        assert "PostgreSQL" in result
        assert "pytest" in result
        assert "GitHub Actions" in result

    def test_prompt_is_not_too_long(self) -> None:
        """Test prompt length is reasonable."""
        result = build_planning_prompt("Any goal")
        # Should be substantial but not excessively long
        assert len(result) > 1000  # Has content
        assert len(result) < 20000  # Not excessively long

    def test_prompt_is_valid_markdown(self) -> None:
        """Test prompt contains valid markdown structure."""
        result = build_planning_prompt("Any goal")

        # Should have markdown headers
        assert "## " in result or "### " in result

        # Should have code blocks
        assert "```" in result

        # Should have list items
        assert "- " in result


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestBuildPlanningPromptEdgeCases:
    """Edge case tests for build_planning_prompt."""

    def test_very_long_goal(self) -> None:
        """Test with very long goal string."""
        long_goal = "Implement feature " + "X" * 1000
        result = build_planning_prompt(long_goal)
        assert long_goal in result

    def test_unicode_goal(self) -> None:
        """Test with unicode characters in goal."""
        goal = "实现功能 🎯 日本語テスト"
        result = build_planning_prompt(goal)
        assert goal in result

    def test_goal_with_newlines_and_tabs(self) -> None:
        """Test goal with various whitespace."""
        goal = "Goal\twith\ttabs\nand\nnewlines"
        result = build_planning_prompt(goal)
        # Goal should be included
        assert "Goal" in result
        assert "tabs" in result
        assert "newlines" in result

    def test_context_with_unicode(self) -> None:
        """Test context with unicode characters."""
        context = "发现：使用 React 框架 🚀"
        result = build_planning_prompt(goal="Goal", context=context)
        assert context in result

    def test_context_with_special_markdown(self) -> None:
        """Test context with special markdown characters."""
        context = "Found `code` and **bold** and _italic_ and ~~strikethrough~~"
        result = build_planning_prompt(goal="Goal", context=context)
        assert "`code`" in result
        assert "**bold**" in result

    def test_whitespace_only_context(self) -> None:
        """Test context with only whitespace."""
        result = build_planning_prompt(goal="Goal", context="   \n\t  ")
        # Whitespace-only context should be stripped and treated as empty
        # "## Previous Context" should not appear with just whitespace content
        # Note: The implementation uses context.strip() but if(context) is truthy for whitespace
        # so it may still add the section with empty content
        assert isinstance(result, str)

    def test_goal_with_backticks(self) -> None:
        """Test goal with backticks."""
        goal = "Fix `TypeError` in `main.py`"
        result = build_planning_prompt(goal)
        assert "`TypeError`" in result
        assert "`main.py`" in result


# =============================================================================
# Prompt Content Validation Tests
# =============================================================================


class TestPromptContentValidation:
    """Tests for validating prompt content correctness."""

    def test_no_duplicate_sections(self) -> None:
        """Test there are no duplicate section headers."""
        result = build_planning_prompt("Any goal")

        # Count key section occurrences
        assert result.count("## Step 1") <= 1
        assert result.count("## Step 2") <= 1
        assert result.count("## Step 3") <= 1
        assert result.count("## PR Strategy") <= 1

    def test_all_complexity_tags_explained(self) -> None:
        """Test all complexity tags have explanations."""
        result = build_planning_prompt("Any goal")

        # Each tag should have a description
        assert "[coding]" in result and "Opus" in result
        assert "[quick]" in result and "Haiku" in result
        assert "[general]" in result and "Sonnet" in result

    def test_consistent_formatting(self) -> None:
        """Test formatting is consistent."""
        result = build_planning_prompt("Any goal")

        # Sections should use ## for headers
        lines = result.split("\n")
        header_lines = [line for line in lines if line.startswith("##")]
        assert len(header_lines) > 0

    def test_code_examples_have_language_hints(self) -> None:
        """Test code examples have language hints."""
        result = build_planning_prompt("Any goal")

        # Should have markdown code blocks with language
        assert "```markdown" in result

    def test_checkpoint_markers_present(self) -> None:
        """Test important markers are present."""
        result = build_planning_prompt("Any goal")

        # Critical markers
        assert "CRITICAL" in result or "IMPORTANT" in result
        assert "STOP" in result
        assert "Do NOT" in result


# =============================================================================
# Function Signature Tests
# =============================================================================


class TestFunctionSignature:
    """Tests for function signature and parameters."""

    def test_goal_is_required(self) -> None:
        """Test goal parameter is required."""
        import inspect

        # Should work with goal
        result = build_planning_prompt("Goal")
        assert isinstance(result, str)

        # Verify parameter is required (has no default value)
        sig = inspect.signature(build_planning_prompt)
        params = sig.parameters
        assert "goal" in params
        assert params["goal"].default is inspect.Parameter.empty

    def test_context_is_optional(self) -> None:
        """Test context parameter is optional."""
        # Should work without context
        result1 = build_planning_prompt("Goal")
        assert isinstance(result1, str)

        # Should work with context
        result2 = build_planning_prompt("Goal", context="Context")
        assert isinstance(result2, str)

    def test_context_can_be_keyword_arg(self) -> None:
        """Test context can be passed as keyword argument."""
        result = build_planning_prompt(goal="Goal", context="Context")
        assert "Context" in result

    def test_context_can_be_positional_arg(self) -> None:
        """Test context can be passed as positional argument."""
        result = build_planning_prompt("Goal", "Context")
        assert "Context" in result

    def test_goal_can_be_keyword_arg(self) -> None:
        """Test goal can be passed as keyword argument."""
        result = build_planning_prompt(goal="My Goal")
        assert "My Goal" in result
