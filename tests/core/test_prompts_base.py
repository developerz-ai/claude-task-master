"""Tests for base prompt components.

This module tests the foundational classes for building prompts:
- PromptSection: A section with title and content
- PromptBuilder: Builds prompts from multiple sections
"""

from dataclasses import fields

from claude_task_master.core.prompts_base import PromptBuilder, PromptSection

# =============================================================================
# PromptSection Dataclass Tests
# =============================================================================


class TestPromptSectionDataclass:
    """Tests for PromptSection as a dataclass."""

    def test_is_dataclass(self) -> None:
        """Test PromptSection is a proper dataclass."""
        section = PromptSection(title="Test", content="Content")
        # Should have __dataclass_fields__
        assert hasattr(section, "__dataclass_fields__")

    def test_has_title_field(self) -> None:
        """Test PromptSection has title field."""
        field_names = [f.name for f in fields(PromptSection)]
        assert "title" in field_names

    def test_has_content_field(self) -> None:
        """Test PromptSection has content field."""
        field_names = [f.name for f in fields(PromptSection)]
        assert "content" in field_names

    def test_has_include_if_field(self) -> None:
        """Test PromptSection has include_if field."""
        field_names = [f.name for f in fields(PromptSection)]
        assert "include_if" in field_names

    def test_required_fields_only(self) -> None:
        """Test PromptSection can be created with required fields only."""
        section = PromptSection(title="Title", content="Content")
        assert section.title == "Title"
        assert section.content == "Content"

    def test_all_fields(self) -> None:
        """Test PromptSection with all fields specified."""
        section = PromptSection(title="Title", content="Content", include_if=False)
        assert section.title == "Title"
        assert section.content == "Content"
        assert section.include_if is False

    def test_default_include_if_is_true(self) -> None:
        """Test include_if defaults to True."""
        section = PromptSection(title="Title", content="Content")
        assert section.include_if is True

    def test_equality(self) -> None:
        """Test PromptSection equality comparison."""
        section1 = PromptSection(title="A", content="B")
        section2 = PromptSection(title="A", content="B")
        section3 = PromptSection(title="A", content="C")
        assert section1 == section2
        assert section1 != section3

    def test_repr(self) -> None:
        """Test PromptSection repr."""
        section = PromptSection(title="Title", content="Content")
        repr_str = repr(section)
        assert "PromptSection" in repr_str
        assert "Title" in repr_str

    def test_mutable_by_default(self) -> None:
        """Test PromptSection is mutable (not frozen)."""
        section = PromptSection(title="Title", content="Content")
        # Should not raise FrozenInstanceError
        section.title = "New Title"
        assert section.title == "New Title"


# =============================================================================
# PromptSection.render() Tests
# =============================================================================


class TestPromptSectionRender:
    """Tests for PromptSection.render() method."""

    def test_render_basic(self) -> None:
        """Test basic section rendering."""
        section = PromptSection(
            title="Test Section",
            content="This is the content.",
        )
        result = section.render()
        assert "## Test Section" in result
        assert "This is the content." in result

    def test_render_format_structure(self) -> None:
        """Test render produces correct markdown structure."""
        section = PromptSection(title="Title", content="Content")
        result = section.render()
        # Should be: ## Title\n\nContent
        assert result == "## Title\n\nContent"

    def test_render_excluded_returns_empty(self) -> None:
        """Test section excluded when include_if is False."""
        section = PromptSection(
            title="Hidden Section",
            content="This should not appear.",
            include_if=False,
        )
        result = section.render()
        assert result == ""

    def test_render_included_returns_content(self) -> None:
        """Test section included when include_if is True."""
        section = PromptSection(
            title="Visible",
            content="This should appear.",
            include_if=True,
        )
        result = section.render()
        assert "Visible" in result
        assert "This should appear." in result

    def test_render_empty_title(self) -> None:
        """Test render with empty title."""
        section = PromptSection(title="", content="Content only")
        result = section.render()
        assert "## \n\nContent only" == result

    def test_render_empty_content(self) -> None:
        """Test render with empty content."""
        section = PromptSection(title="Title Only", content="")
        result = section.render()
        assert "## Title Only\n\n" == result

    def test_render_multiline_content(self) -> None:
        """Test render with multiline content."""
        section = PromptSection(
            title="Multi",
            content="Line 1\nLine 2\nLine 3",
        )
        result = section.render()
        assert "## Multi" in result
        assert "Line 1\nLine 2\nLine 3" in result

    def test_render_content_with_markdown(self) -> None:
        """Test render preserves markdown in content."""
        section = PromptSection(
            title="Markdown",
            content="- Item 1\n- Item 2\n\n**Bold** and *italic*",
        )
        result = section.render()
        assert "- Item 1" in result
        assert "**Bold**" in result

    def test_render_title_with_special_chars(self) -> None:
        """Test render with special characters in title."""
        section = PromptSection(
            title="Test: 1/2 & More",
            content="Content",
        )
        result = section.render()
        assert "## Test: 1/2 & More" in result

    def test_render_content_with_code_block(self) -> None:
        """Test render with code block in content."""
        section = PromptSection(
            title="Code Example",
            content="```python\nprint('hello')\n```",
        )
        result = section.render()
        assert "```python" in result
        assert "print('hello')" in result

    def test_render_returns_string(self) -> None:
        """Test render always returns a string."""
        section1 = PromptSection(title="A", content="B")
        section2 = PromptSection(title="A", content="B", include_if=False)
        assert isinstance(section1.render(), str)
        assert isinstance(section2.render(), str)


# =============================================================================
# PromptBuilder Dataclass Tests
# =============================================================================


class TestPromptBuilderDataclass:
    """Tests for PromptBuilder as a dataclass."""

    def test_is_dataclass(self) -> None:
        """Test PromptBuilder is a proper dataclass."""
        builder = PromptBuilder()
        assert hasattr(builder, "__dataclass_fields__")

    def test_has_intro_field(self) -> None:
        """Test PromptBuilder has intro field."""
        field_names = [f.name for f in fields(PromptBuilder)]
        assert "intro" in field_names

    def test_has_sections_field(self) -> None:
        """Test PromptBuilder has sections field."""
        field_names = [f.name for f in fields(PromptBuilder)]
        assert "sections" in field_names

    def test_default_empty_intro(self) -> None:
        """Test intro defaults to empty string."""
        builder = PromptBuilder()
        assert builder.intro == ""

    def test_default_empty_sections(self) -> None:
        """Test sections defaults to empty list."""
        builder = PromptBuilder()
        assert builder.sections == []
        assert isinstance(builder.sections, list)

    def test_with_intro(self) -> None:
        """Test creating with intro."""
        builder = PromptBuilder(intro="Welcome to the prompt.")
        assert builder.intro == "Welcome to the prompt."

    def test_with_sections(self) -> None:
        """Test creating with pre-populated sections."""
        sections = [
            PromptSection(title="A", content="a"),
            PromptSection(title="B", content="b"),
        ]
        builder = PromptBuilder(sections=sections)
        assert len(builder.sections) == 2
        assert builder.sections[0].title == "A"

    def test_sections_are_independent(self) -> None:
        """Test sections list is independent per instance."""
        builder1 = PromptBuilder()
        builder2 = PromptBuilder()
        builder1.add_section("A", "a")
        assert len(builder1.sections) == 1
        assert len(builder2.sections) == 0


# =============================================================================
# PromptBuilder.add_section() Tests
# =============================================================================


class TestPromptBuilderAddSection:
    """Tests for PromptBuilder.add_section() method."""

    def test_add_section_creates_section(self) -> None:
        """Test add_section creates a PromptSection."""
        builder = PromptBuilder()
        builder.add_section("Title", "Content")
        assert len(builder.sections) == 1
        assert isinstance(builder.sections[0], PromptSection)

    def test_add_section_with_title_and_content(self) -> None:
        """Test add_section sets title and content."""
        builder = PromptBuilder()
        builder.add_section("My Title", "My Content")
        section = builder.sections[0]
        assert section.title == "My Title"
        assert section.content == "My Content"

    def test_add_section_include_if_true_default(self) -> None:
        """Test add_section defaults include_if to True."""
        builder = PromptBuilder()
        builder.add_section("Title", "Content")
        assert builder.sections[0].include_if is True

    def test_add_section_include_if_false(self) -> None:
        """Test add_section with include_if=False."""
        builder = PromptBuilder()
        builder.add_section("Hidden", "Content", include_if=False)
        assert builder.sections[0].include_if is False

    def test_add_section_returns_self(self) -> None:
        """Test add_section returns the builder for chaining."""
        builder = PromptBuilder()
        result = builder.add_section("Title", "Content")
        assert result is builder

    def test_method_chaining(self) -> None:
        """Test add_section supports method chaining."""
        builder = PromptBuilder()
        result = builder.add_section("A", "a").add_section("B", "b").add_section("C", "c")
        assert result is builder
        assert len(builder.sections) == 3

    def test_add_multiple_sections(self) -> None:
        """Test adding multiple sections."""
        builder = PromptBuilder()
        builder.add_section("First", "1")
        builder.add_section("Second", "2")
        builder.add_section("Third", "3")
        assert len(builder.sections) == 3
        assert builder.sections[0].title == "First"
        assert builder.sections[1].title == "Second"
        assert builder.sections[2].title == "Third"

    def test_add_section_preserves_order(self) -> None:
        """Test sections maintain insertion order."""
        builder = PromptBuilder()
        builder.add_section("Z", "last")
        builder.add_section("A", "first")
        builder.add_section("M", "middle")
        assert builder.sections[0].title == "Z"
        assert builder.sections[1].title == "A"
        assert builder.sections[2].title == "M"

    def test_add_section_empty_title(self) -> None:
        """Test adding section with empty title."""
        builder = PromptBuilder()
        builder.add_section("", "Content")
        assert builder.sections[0].title == ""

    def test_add_section_empty_content(self) -> None:
        """Test adding section with empty content."""
        builder = PromptBuilder()
        builder.add_section("Title", "")
        assert builder.sections[0].content == ""


# =============================================================================
# PromptBuilder.build() Tests
# =============================================================================


class TestPromptBuilderBuild:
    """Tests for PromptBuilder.build() method."""

    def test_build_empty_builder(self) -> None:
        """Test building with no intro and no sections."""
        builder = PromptBuilder()
        result = builder.build()
        assert result == ""

    def test_build_intro_only(self) -> None:
        """Test building with only intro."""
        builder = PromptBuilder(intro="Welcome to the prompt.")
        result = builder.build()
        assert result == "Welcome to the prompt."

    def test_build_single_section(self) -> None:
        """Test building with a single section."""
        builder = PromptBuilder()
        builder.add_section("Section", "Content")
        result = builder.build()
        assert "## Section" in result
        assert "Content" in result

    def test_build_intro_and_section(self) -> None:
        """Test building with intro and section."""
        builder = PromptBuilder(intro="Intro text")
        builder.add_section("Section", "Content")
        result = builder.build()
        assert "Intro text" in result
        assert "## Section" in result
        assert result.index("Intro text") < result.index("## Section")

    def test_build_multiple_sections(self) -> None:
        """Test building with multiple sections."""
        builder = PromptBuilder(intro="Intro")
        builder.add_section("Section A", "Content A")
        builder.add_section("Section B", "Content B")
        result = builder.build()

        assert "Intro" in result
        assert "## Section A" in result
        assert "## Section B" in result
        # Verify order
        assert result.index("Section A") < result.index("Section B")

    def test_build_sections_separated_by_double_newline(self) -> None:
        """Test sections are separated by double newlines."""
        builder = PromptBuilder()
        builder.add_section("A", "a")
        builder.add_section("B", "b")
        result = builder.build()
        # Sections should be joined by \n\n
        assert "## A\n\na\n\n## B\n\nb" == result

    def test_build_excludes_false_include_if(self) -> None:
        """Test build excludes sections with include_if=False."""
        builder = PromptBuilder()
        builder.add_section("Included", "yes", include_if=True)
        builder.add_section("Excluded", "no", include_if=False)
        result = builder.build()

        assert "Included" in result
        assert "yes" in result
        assert "Excluded" not in result
        assert "no" not in result

    def test_build_all_excluded_returns_empty(self) -> None:
        """Test build returns empty when all sections excluded."""
        builder = PromptBuilder()
        builder.add_section("A", "a", include_if=False)
        builder.add_section("B", "b", include_if=False)
        result = builder.build()
        assert result == ""

    def test_build_returns_string(self) -> None:
        """Test build always returns a string."""
        builder1 = PromptBuilder()
        builder2 = PromptBuilder(intro="intro")
        builder3 = PromptBuilder()
        builder3.add_section("A", "a")

        assert isinstance(builder1.build(), str)
        assert isinstance(builder2.build(), str)
        assert isinstance(builder3.build(), str)

    def test_build_with_intro_and_all_excluded(self) -> None:
        """Test build with intro but all sections excluded."""
        builder = PromptBuilder(intro="Just intro")
        builder.add_section("Excluded", "content", include_if=False)
        result = builder.build()
        assert result == "Just intro"

    def test_build_multiline_intro(self) -> None:
        """Test build with multiline intro."""
        builder = PromptBuilder(intro="Line 1\nLine 2\nLine 3")
        builder.add_section("Section", "Content")
        result = builder.build()
        assert "Line 1\nLine 2\nLine 3" in result

    def test_build_idempotent(self) -> None:
        """Test build can be called multiple times with same result."""
        builder = PromptBuilder(intro="Intro")
        builder.add_section("Section", "Content")
        result1 = builder.build()
        result2 = builder.build()
        assert result1 == result2

    def test_build_does_not_modify_builder(self) -> None:
        """Test build does not modify the builder state."""
        builder = PromptBuilder(intro="Intro")
        builder.add_section("Section", "Content")
        sections_before = len(builder.sections)
        intro_before = builder.intro

        builder.build()

        assert len(builder.sections) == sections_before
        assert builder.intro == intro_before


# =============================================================================
# Integration Tests
# =============================================================================


class TestPromptBuilderIntegration:
    """Integration tests for complete prompt building workflows."""

    def test_complex_prompt_building(self) -> None:
        """Test building a complex prompt with multiple sections."""
        builder = PromptBuilder(intro="You are a helpful assistant.")
        builder.add_section("Task", "Complete the following task.")
        builder.add_section("Context", "Here is some context.", include_if=True)
        builder.add_section("Hidden", "Skip this", include_if=False)
        builder.add_section("Requirements", "- Requirement 1\n- Requirement 2")

        result = builder.build()

        assert "You are a helpful assistant." in result
        assert "## Task" in result
        assert "## Context" in result
        assert "Hidden" not in result
        assert "## Requirements" in result
        assert "- Requirement 1" in result

    def test_conditional_section_based_on_variable(self) -> None:
        """Test adding sections conditionally based on variables."""
        has_context = True
        has_history = False

        builder = PromptBuilder()
        builder.add_section("Main", "Main content")
        builder.add_section("Context", "Context info", include_if=has_context)
        builder.add_section("History", "History info", include_if=has_history)

        result = builder.build()
        assert "Context" in result
        assert "History" not in result

    def test_fluent_api(self) -> None:
        """Test fluent API pattern."""
        result = (
            PromptBuilder(intro="Intro")
            .add_section("Section 1", "Content 1")
            .add_section("Section 2", "Content 2")
            .add_section("Section 3", "Content 3")
            .build()
        )

        assert "Intro" in result
        assert "Section 1" in result
        assert "Section 2" in result
        assert "Section 3" in result

    def test_reusable_builder(self) -> None:
        """Test builder can be reused after adding more sections."""
        builder = PromptBuilder(intro="Base")
        builder.add_section("Core", "Core content")

        # First build
        result1 = builder.build()
        assert "Core" in result1

        # Add more and build again
        builder.add_section("Extra", "Extra content")
        result2 = builder.build()
        assert "Core" in result2
        assert "Extra" in result2

    def test_prompt_section_reuse(self) -> None:
        """Test reusing PromptSection instances."""
        shared_section = PromptSection(title="Shared", content="Shared content")

        builder1 = PromptBuilder()
        builder1.sections.append(shared_section)

        builder2 = PromptBuilder()
        builder2.sections.append(shared_section)

        assert builder1.build() == builder2.build()


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Edge case tests for prompt components."""

    def test_section_with_unicode(self) -> None:
        """Test section with unicode characters."""
        section = PromptSection(
            title="日本語タイトル",
            content="Content with emojis 🎯✓⚠️",
        )
        result = section.render()
        assert "日本語タイトル" in result
        assert "🎯" in result

    def test_section_with_long_content(self) -> None:
        """Test section with very long content."""
        long_content = "A" * 10000
        section = PromptSection(title="Long", content=long_content)
        result = section.render()
        assert len(result) > 10000
        assert long_content in result

    def test_builder_with_many_sections(self) -> None:
        """Test builder with many sections."""
        builder = PromptBuilder()
        for i in range(100):
            builder.add_section(f"Section {i}", f"Content {i}")

        result = builder.build()
        assert "Section 0" in result
        assert "Section 99" in result

    def test_section_with_nested_markdown_headers(self) -> None:
        """Test section content can contain headers."""
        section = PromptSection(
            title="Main",
            content="### Subsection\nContent\n#### Sub-subsection\nMore content",
        )
        result = section.render()
        assert "## Main" in result
        assert "### Subsection" in result
        assert "#### Sub-subsection" in result

    def test_empty_intro_and_one_excluded_section(self) -> None:
        """Test empty intro with all sections excluded."""
        builder = PromptBuilder(intro="")
        builder.add_section("Excluded", "content", include_if=False)
        result = builder.build()
        assert result == ""

    def test_whitespace_in_title_and_content(self) -> None:
        """Test handling of whitespace."""
        section = PromptSection(
            title="  Title with spaces  ",
            content="  Content with spaces  ",
        )
        result = section.render()
        # Should preserve whitespace
        assert "  Title with spaces  " in result
        assert "  Content with spaces  " in result

    def test_newlines_in_title(self) -> None:
        """Test handling of newlines in title (unusual but should work)."""
        section = PromptSection(
            title="Title\nwith\nnewlines",
            content="Content",
        )
        result = section.render()
        assert "## Title\nwith\nnewlines" in result

    def test_section_with_only_whitespace_content(self) -> None:
        """Test section with whitespace-only content."""
        section = PromptSection(title="Title", content="   \n\t  \n  ")
        result = section.render()
        assert "## Title" in result

    def test_builder_sections_list_modification(self) -> None:
        """Test directly modifying sections list."""
        builder = PromptBuilder()
        builder.sections.append(PromptSection(title="Direct", content="Content"))
        result = builder.build()
        assert "Direct" in result


# =============================================================================
# Type and Structure Tests
# =============================================================================


class TestTypeAndStructure:
    """Tests for type correctness and structure."""

    def test_prompt_section_title_is_str(self) -> None:
        """Test PromptSection title is a string."""
        section = PromptSection(title="Title", content="Content")
        assert isinstance(section.title, str)

    def test_prompt_section_content_is_str(self) -> None:
        """Test PromptSection content is a string."""
        section = PromptSection(title="Title", content="Content")
        assert isinstance(section.content, str)

    def test_prompt_section_include_if_is_bool(self) -> None:
        """Test PromptSection include_if is a boolean."""
        section = PromptSection(title="Title", content="Content")
        assert isinstance(section.include_if, bool)

    def test_prompt_builder_intro_is_str(self) -> None:
        """Test PromptBuilder intro is a string."""
        builder = PromptBuilder()
        assert isinstance(builder.intro, str)

    def test_prompt_builder_sections_is_list(self) -> None:
        """Test PromptBuilder sections is a list."""
        builder = PromptBuilder()
        assert isinstance(builder.sections, list)

    def test_prompt_builder_sections_contain_prompt_sections(self) -> None:
        """Test PromptBuilder sections list contains PromptSection objects."""
        builder = PromptBuilder()
        builder.add_section("A", "a")
        builder.add_section("B", "b")
        for section in builder.sections:
            assert isinstance(section, PromptSection)


# =============================================================================
# Real-World Usage Pattern Tests
# =============================================================================


class TestRealWorldPatterns:
    """Tests mimicking real-world usage patterns."""

    def test_planning_prompt_pattern(self) -> None:
        """Test pattern used for planning prompts."""
        goal = "Build a todo app"
        context = "Using React and TypeScript"

        builder = PromptBuilder(intro="You are planning a software project.")
        builder.add_section("Goal", goal)
        builder.add_section("Context", context, include_if=bool(context))
        builder.add_section("Instructions", "Create a task list with checkboxes.")

        result = builder.build()
        assert "planning" in result.lower()
        assert "Build a todo app" in result
        assert "React and TypeScript" in result
        assert "checkboxes" in result

    def test_work_prompt_pattern(self) -> None:
        """Test pattern used for work prompts."""
        task = "Implement user authentication"
        pr_comments = ""  # No PR comments
        file_hints = ["src/auth.py", "tests/test_auth.py"]

        builder = PromptBuilder()
        builder.add_section("Current Task", task)
        builder.add_section("PR Review Feedback", pr_comments, include_if=bool(pr_comments))
        builder.add_section("Relevant Files", "\n".join(f"- {f}" for f in file_hints))

        result = builder.build()
        assert "Current Task" in result
        assert "user authentication" in result
        assert "PR Review Feedback" not in result  # Empty, should be excluded
        assert "src/auth.py" in result

    def test_verification_prompt_pattern(self) -> None:
        """Test pattern used for verification prompts."""
        criteria = "All tests pass\nNo linting errors"
        tasks_summary = "Implemented login feature"

        builder = PromptBuilder()
        builder.add_section("Success Criteria", criteria)
        builder.add_section("Completed Tasks", tasks_summary, include_if=bool(tasks_summary))
        builder.add_section("Instructions", "Verify each criterion.")

        result = builder.build()
        assert "Success Criteria" in result
        assert "All tests pass" in result
        assert "Completed Tasks" in result
        assert "Verify" in result

    def test_dynamic_section_inclusion(self) -> None:
        """Test dynamically including sections based on data presence."""

        def build_prompt(
            task: str,
            context: str | None = None,
            hints: list[str] | None = None,
        ) -> str:
            builder = PromptBuilder()
            builder.add_section("Task", task)
            builder.add_section("Context", context or "", include_if=context is not None)
            builder.add_section(
                "Hints",
                "\n".join(hints) if hints else "",
                include_if=hints is not None and len(hints) > 0,
            )
            return builder.build()

        # All sections
        result1 = build_prompt("Task 1", "Context 1", ["Hint 1", "Hint 2"])
        assert "Context" in result1
        assert "Hints" in result1

        # Only task
        result2 = build_prompt("Task 2")
        assert "Task 2" in result2
        assert "Context" not in result2
        assert "Hints" not in result2

        # Task with empty hints list
        result3 = build_prompt("Task 3", hints=[])
        assert "Task 3" in result3
        assert "Hints" not in result3
