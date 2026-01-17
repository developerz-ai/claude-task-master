"""Tests for the agent_models module.

This module tests:
- ModelType enum
- TaskComplexity enum
- ToolConfig enum
- MODEL_CONTEXT_WINDOWS constants
- parse_task_complexity function
"""

import pytest

from claude_task_master.core.agent_models import (
    DEFAULT_COMPACT_THRESHOLD_PERCENT,
    MODEL_CONTEXT_WINDOWS,
    MODEL_CONTEXT_WINDOWS_STANDARD,
    ModelType,
    TaskComplexity,
    ToolConfig,
    parse_task_complexity,
)

# =============================================================================
# ModelType Enum Tests
# =============================================================================


class TestModelType:
    """Tests for ModelType enum."""

    def test_sonnet_value(self):
        """Test SONNET model value."""
        assert ModelType.SONNET.value == "sonnet"

    def test_opus_value(self):
        """Test OPUS model value."""
        assert ModelType.OPUS.value == "opus"

    def test_haiku_value(self):
        """Test HAIKU model value."""
        assert ModelType.HAIKU.value == "haiku"

    def test_model_type_from_string(self):
        """Test creating ModelType from string value."""
        assert ModelType("sonnet") == ModelType.SONNET
        assert ModelType("opus") == ModelType.OPUS
        assert ModelType("haiku") == ModelType.HAIKU

    def test_invalid_model_type(self):
        """Test invalid model type raises ValueError."""
        with pytest.raises(ValueError):
            ModelType("invalid-model")

    def test_all_model_types(self):
        """Test all expected model types exist."""
        expected = {"SONNET", "OPUS", "HAIKU"}
        actual = {m.name for m in ModelType}
        assert actual == expected


# =============================================================================
# TaskComplexity Enum Tests
# =============================================================================


class TestTaskComplexity:
    """Tests for TaskComplexity enum."""

    def test_coding_value(self):
        """Test CODING complexity value."""
        assert TaskComplexity.CODING.value == "coding"

    def test_quick_value(self):
        """Test QUICK complexity value."""
        assert TaskComplexity.QUICK.value == "quick"

    def test_general_value(self):
        """Test GENERAL complexity value."""
        assert TaskComplexity.GENERAL.value == "general"

    def test_complexity_from_string(self):
        """Test creating TaskComplexity from string value."""
        assert TaskComplexity("coding") == TaskComplexity.CODING
        assert TaskComplexity("quick") == TaskComplexity.QUICK
        assert TaskComplexity("general") == TaskComplexity.GENERAL

    def test_invalid_complexity(self):
        """Test invalid complexity raises ValueError."""
        with pytest.raises(ValueError):
            TaskComplexity("invalid")

    def test_all_complexity_levels(self):
        """Test all expected complexity levels exist."""
        expected = {"CODING", "QUICK", "GENERAL"}
        actual = {c.name for c in TaskComplexity}
        assert actual == expected

    def test_get_model_for_coding_complexity(self):
        """Test CODING complexity maps to OPUS."""
        model = TaskComplexity.get_model_for_complexity(TaskComplexity.CODING)
        assert model == ModelType.OPUS

    def test_get_model_for_quick_complexity(self):
        """Test QUICK complexity maps to HAIKU."""
        model = TaskComplexity.get_model_for_complexity(TaskComplexity.QUICK)
        assert model == ModelType.HAIKU

    def test_get_model_for_general_complexity(self):
        """Test GENERAL complexity maps to SONNET."""
        model = TaskComplexity.get_model_for_complexity(TaskComplexity.GENERAL)
        assert model == ModelType.SONNET


# =============================================================================
# ToolConfig Enum Tests
# =============================================================================


class TestToolConfig:
    """Tests for ToolConfig enum."""

    def test_planning_tools(self):
        """Test PLANNING tool configuration - read-only tools for exploration."""
        expected = [
            "Read",
            "Glob",
            "Grep",
            "Bash",
        ]
        assert ToolConfig.PLANNING.value == expected

    def test_working_tools(self):
        """Test WORKING tool configuration."""
        expected = [
            "Read",
            "Write",
            "Edit",
            "Bash",
            "Glob",
            "Grep",
            "Task",
            "TodoWrite",
            "WebSearch",
            "WebFetch",
            "Skill",
        ]
        assert ToolConfig.WORKING.value == expected

    def test_verification_tools(self):
        """Test VERIFICATION tool configuration - read tools + Bash for running tests."""
        expected = [
            "Read",
            "Glob",
            "Grep",
            "Bash",
        ]
        assert ToolConfig.VERIFICATION.value == expected

    def test_planning_has_subset_of_working_tools(self):
        """Test planning tools are a subset of working tools (read-only)."""
        planning_tools = set(ToolConfig.PLANNING.value)
        working_tools = set(ToolConfig.WORKING.value)
        assert planning_tools.issubset(working_tools)
        assert planning_tools != working_tools  # Planning is restricted

    def test_verification_has_subset_of_working_tools(self):
        """Test verification tools are a subset of working tools."""
        verification_tools = set(ToolConfig.VERIFICATION.value)
        working_tools = set(ToolConfig.WORKING.value)
        assert verification_tools.issubset(working_tools)
        # Verification has Bash but no Write/Edit
        assert "Bash" in verification_tools
        assert "Write" not in verification_tools
        assert "Edit" not in verification_tools

    def test_planning_does_not_have_write_tools(self):
        """Test planning phase doesn't have write tools."""
        planning_tools = ToolConfig.PLANNING.value
        assert "Write" not in planning_tools
        assert "Edit" not in planning_tools

    def test_working_has_write_tools(self):
        """Test working phase has write tools."""
        working_tools = ToolConfig.WORKING.value
        assert "Write" in working_tools
        assert "Edit" in working_tools


# =============================================================================
# Model Context Window Constants Tests
# =============================================================================


class TestModelContextWindows:
    """Tests for MODEL_CONTEXT_WINDOWS constants."""

    def test_all_models_have_context_windows(self):
        """Test all ModelType values have context window entries."""
        for model in ModelType:
            assert model in MODEL_CONTEXT_WINDOWS
            assert model in MODEL_CONTEXT_WINDOWS_STANDARD

    def test_opus_context_window(self):
        """Test Opus context window is 200K."""
        assert MODEL_CONTEXT_WINDOWS[ModelType.OPUS] == 200_000

    def test_sonnet_context_window_tier4(self):
        """Test Sonnet context window is 1M for tier 4+."""
        assert MODEL_CONTEXT_WINDOWS[ModelType.SONNET] == 1_000_000

    def test_sonnet_context_window_standard(self):
        """Test Sonnet standard context window is 200K."""
        assert MODEL_CONTEXT_WINDOWS_STANDARD[ModelType.SONNET] == 200_000

    def test_haiku_context_window(self):
        """Test Haiku context window is 200K."""
        assert MODEL_CONTEXT_WINDOWS[ModelType.HAIKU] == 200_000

    def test_context_windows_are_positive(self):
        """Test all context windows are positive integers."""
        for model in ModelType:
            assert MODEL_CONTEXT_WINDOWS[model] > 0
            assert MODEL_CONTEXT_WINDOWS_STANDARD[model] > 0

    def test_default_compact_threshold(self):
        """Test default compact threshold is 0.85 (85%)."""
        assert DEFAULT_COMPACT_THRESHOLD_PERCENT == 0.85


# =============================================================================
# parse_task_complexity Tests
# =============================================================================


class TestParseTaskComplexity:
    """Tests for parse_task_complexity function."""

    def test_parse_coding_tag(self):
        """Test parsing `[coding]` tag."""
        task = "Implement feature `[coding]` with full tests"
        complexity, cleaned = parse_task_complexity(task)

        assert complexity == TaskComplexity.CODING
        assert "Implement feature" in cleaned
        assert "with full tests" in cleaned
        assert "`[coding]`" not in cleaned

    def test_parse_quick_tag(self):
        """Test parsing `[quick]` tag."""
        task = "`[quick]` Fix typo in README"
        complexity, cleaned = parse_task_complexity(task)

        assert complexity == TaskComplexity.QUICK
        assert "Fix typo in README" in cleaned
        assert "`[quick]`" not in cleaned

    def test_parse_general_tag(self):
        """Test parsing `[general]` tag."""
        task = "Update dependencies `[general]`"
        complexity, cleaned = parse_task_complexity(task)

        assert complexity == TaskComplexity.GENERAL
        assert "Update dependencies" in cleaned
        assert "`[general]`" not in cleaned

    def test_parse_uppercase_tag(self):
        """Test parsing uppercase tag (case insensitive)."""
        task = "Implement feature `[CODING]`"
        complexity, cleaned = parse_task_complexity(task)

        assert complexity == TaskComplexity.CODING

    def test_parse_mixed_case_tag(self):
        """Test parsing mixed case tag."""
        task = "Fix bug `[QuIcK]`"
        complexity, cleaned = parse_task_complexity(task)

        assert complexity == TaskComplexity.QUICK

    def test_parse_no_tag_defaults_to_coding(self):
        """Test no tag defaults to CODING (prefer smarter model)."""
        task = "Implement user authentication"
        complexity, cleaned = parse_task_complexity(task)

        assert complexity == TaskComplexity.CODING
        assert cleaned == task

    def test_parse_empty_string(self):
        """Test parsing empty string."""
        task = ""
        complexity, cleaned = parse_task_complexity(task)

        assert complexity == TaskComplexity.CODING
        assert cleaned == ""

    def test_parse_tag_at_start(self):
        """Test tag at start of description."""
        task = "`[quick]` Fix small bug"
        complexity, cleaned = parse_task_complexity(task)

        assert complexity == TaskComplexity.QUICK
        assert cleaned == "Fix small bug"

    def test_parse_tag_at_end(self):
        """Test tag at end of description."""
        task = "Fix small bug `[quick]`"
        complexity, cleaned = parse_task_complexity(task)

        assert complexity == TaskComplexity.QUICK
        assert cleaned == "Fix small bug"

    def test_parse_tag_in_middle(self):
        """Test tag in middle of description."""
        task = "Fix small `[quick]` bug quickly"
        complexity, cleaned = parse_task_complexity(task)

        assert complexity == TaskComplexity.QUICK
        # Tag is removed, surrounding text is preserved
        assert "Fix small" in cleaned
        assert "bug quickly" in cleaned

    def test_parse_preserves_other_backticks(self):
        """Test other backticks in description are preserved."""
        task = "Fix `config.py` issue `[quick]`"
        complexity, cleaned = parse_task_complexity(task)

        assert complexity == TaskComplexity.QUICK
        assert "`config.py`" in cleaned

    def test_parse_tag_without_backticks_not_matched(self):
        """Test tag without backticks is not matched."""
        task = "Implement feature [coding] without backticks"
        complexity, cleaned = parse_task_complexity(task)

        # Should default to CODING since no backtick-wrapped tag
        assert complexity == TaskComplexity.CODING
        assert cleaned == task  # Unchanged

    def test_parse_multiple_tags_uses_first(self):
        """Test multiple tags uses first match."""
        task = "`[quick]` then `[coding]` task"
        complexity, cleaned = parse_task_complexity(task)

        # First match is used
        assert complexity == TaskComplexity.QUICK


# =============================================================================
# Backward Compatibility Tests
# =============================================================================


class TestBackwardCompatibility:
    """Tests for backward compatibility with agent.py imports."""

    def test_import_from_agent_module(self):
        """Test imports from agent.py still work."""
        from claude_task_master.core.agent import (
            ModelType,
            TaskComplexity,
            ToolConfig,
        )

        assert ModelType.SONNET.value == "sonnet"
        assert TaskComplexity.CODING.value == "coding"
        assert "Read" in ToolConfig.PLANNING.value

    def test_import_from_core_init(self):
        """Test imports from core.__init__ work."""
        from claude_task_master.core import (
            DEFAULT_COMPACT_THRESHOLD_PERCENT,
            MODEL_CONTEXT_WINDOWS,
            MODEL_CONTEXT_WINDOWS_STANDARD,
            ModelType,
            TaskComplexity,
            ToolConfig,
            parse_task_complexity,
        )

        assert ModelType.SONNET.value == "sonnet"
        assert TaskComplexity.CODING.value == "coding"
        assert "Read" in ToolConfig.PLANNING.value
        assert MODEL_CONTEXT_WINDOWS[ModelType.SONNET] == 1_000_000
        assert MODEL_CONTEXT_WINDOWS_STANDARD[ModelType.SONNET] == 200_000
        assert DEFAULT_COMPACT_THRESHOLD_PERCENT == 0.85
        assert parse_task_complexity("`[quick]` task")[0] == TaskComplexity.QUICK
