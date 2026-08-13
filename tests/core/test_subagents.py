"""Tests for the subagents module - subagent loading functionality.

This module tests:
- YAML frontmatter parsing from agent markdown files
- Agent loading from .claude/agents/ directory
- CLAUDE.md detection
- Project configuration detection
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.subagents import (
    BUILTIN_AGENT_NAMES,
    HIVE_WORKER_AGENT_NAME,
    HIVE_WORKER_DESCRIPTION,
    HIVE_WORKER_PROMPT,
    build_builtin_agents,
    detect_claude_md,
    detect_project_config,
    get_agents_for_working_dir,
    load_agents_from_directory,
    parse_agent_frontmatter,
)

# Ignore unused variable in test assertions
# ruff: noqa: F841


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def temp_working_dir(tmp_path: Path) -> Path:
    """Create a temporary working directory."""
    return tmp_path


@pytest.fixture
def agents_dir(temp_working_dir: Path) -> Path:
    """Create .claude/agents/ directory structure."""
    agents_path = temp_working_dir / ".claude" / "agents"
    agents_path.mkdir(parents=True)
    return agents_path


@pytest.fixture
def sample_agent_md() -> str:
    """Sample agent markdown with frontmatter."""
    return """---
name: test-agent
description: A test agent for unit testing
model: sonnet
---

This is the agent prompt content.
It can span multiple lines.
"""


@pytest.fixture
def agent_without_description() -> str:
    """Agent markdown without description (invalid)."""
    return """---
name: no-desc-agent
model: haiku
---

Agent prompt content.
"""


@pytest.fixture
def agent_with_tools() -> str:
    """Agent markdown with tools list."""
    return """---
name: tool-agent
description: Agent with specific tools
model: opus
tools: [Read, Glob, Grep]
---

Agent prompt with restricted tools.
"""


# =============================================================================
# parse_agent_frontmatter Tests
# =============================================================================


class TestParseAgentFrontmatter:
    """Tests for parse_agent_frontmatter function."""

    def test_basic_frontmatter_parsing(self) -> None:
        """Test basic YAML frontmatter extraction."""
        content = """---
name: my-agent
description: Test description
model: sonnet
---

Agent prompt content here.
"""
        frontmatter, prompt = parse_agent_frontmatter(content)

        assert frontmatter["name"] == "my-agent"
        assert frontmatter["description"] == "Test description"
        assert frontmatter["model"] == "sonnet"
        assert prompt == "Agent prompt content here."

    def test_no_frontmatter_returns_full_content(self) -> None:
        """Test content without frontmatter returns full content as prompt."""
        content = "Just a plain prompt without any frontmatter."
        frontmatter, prompt = parse_agent_frontmatter(content)

        assert frontmatter == {}
        assert prompt == "Just a plain prompt without any frontmatter."

    def test_empty_frontmatter(self) -> None:
        """Test empty frontmatter block."""
        content = """---

---

Prompt content.
"""
        frontmatter, prompt = parse_agent_frontmatter(content)

        assert frontmatter == {}
        assert prompt == "Prompt content."

    def test_boolean_true_values(self) -> None:
        """Test parsing boolean true values."""
        content = """---
enabled: true
active: yes
---

Prompt.
"""
        frontmatter, prompt = parse_agent_frontmatter(content)

        assert frontmatter["enabled"] is True
        assert frontmatter["active"] is True

    def test_boolean_false_values(self) -> None:
        """Test parsing boolean false values."""
        content = """---
enabled: false
active: no
---

Prompt.
"""
        frontmatter, prompt = parse_agent_frontmatter(content)

        assert frontmatter["enabled"] is False
        assert frontmatter["active"] is False

    def test_list_parsing(self) -> None:
        """Test parsing list values in frontmatter."""
        content = """---
tools: [Read, Glob, Grep]
---

Prompt.
"""
        frontmatter, prompt = parse_agent_frontmatter(content)

        assert frontmatter["tools"] == ["Read", "Glob", "Grep"]

    def test_list_with_quoted_items(self) -> None:
        """Test parsing list with quoted items."""
        content = """---
tools: ["Read", 'Glob', Grep]
---

Prompt.
"""
        frontmatter, prompt = parse_agent_frontmatter(content)

        assert frontmatter["tools"] == ["Read", "Glob", "Grep"]

    def test_comment_lines_ignored(self) -> None:
        """Test that comment lines in frontmatter are ignored."""
        content = """---
name: agent
# This is a comment
description: Test
---

Prompt.
"""
        frontmatter, prompt = parse_agent_frontmatter(content)

        assert "comment" not in frontmatter
        assert frontmatter["name"] == "agent"
        assert frontmatter["description"] == "Test"

    def test_empty_lines_ignored(self) -> None:
        """Test that empty lines in frontmatter are ignored."""
        content = """---
name: agent

description: Test

---

Prompt.
"""
        frontmatter, prompt = parse_agent_frontmatter(content)

        assert frontmatter["name"] == "agent"
        assert frontmatter["description"] == "Test"

    def test_multiline_prompt(self) -> None:
        """Test multiline prompt content is preserved."""
        content = """---
name: agent
---

Line 1
Line 2
Line 3
"""
        frontmatter, prompt = parse_agent_frontmatter(content)

        assert "Line 1" in prompt
        assert "Line 2" in prompt
        assert "Line 3" in prompt

    def test_whitespace_trimming(self) -> None:
        """Test whitespace is trimmed from values."""
        content = """---
name:   spaced-value
description:  has spaces
---

Prompt content.
"""
        frontmatter, prompt = parse_agent_frontmatter(content)

        assert frontmatter["name"] == "spaced-value"
        assert frontmatter["description"] == "has spaces"

    def test_colon_in_value(self) -> None:
        """Test values containing colons are handled."""
        content = """---
name: agent
description: Agent for time: 10:30 AM
---

Prompt.
"""
        frontmatter, prompt = parse_agent_frontmatter(content)

        # Value should be everything after the first colon
        assert "10:30 AM" in frontmatter["description"]

    def test_case_insensitive_boolean(self) -> None:
        """Test boolean parsing is case insensitive."""
        content = """---
a: TRUE
b: True
c: YES
d: FALSE
e: No
---

Prompt.
"""
        frontmatter, _ = parse_agent_frontmatter(content)

        assert frontmatter["a"] is True
        assert frontmatter["b"] is True
        assert frontmatter["c"] is True
        assert frontmatter["d"] is False
        assert frontmatter["e"] is False


# =============================================================================
# load_agents_from_directory Tests
# =============================================================================


class TestLoadAgentsFromDirectory:
    """Tests for load_agents_from_directory function."""

    def test_returns_empty_when_sdk_not_installed(self, temp_working_dir: Path) -> None:
        """Test returns empty dict when SDK is not installed."""
        with patch.dict("sys.modules", {"claude_agent_sdk": None}):
            # Force import error by patching the import
            with patch("claude_task_master.core.subagents.load_agents_from_directory") as mock_load:
                mock_load.return_value = {}
                result = mock_load(str(temp_working_dir))
                assert result == {}

    def test_returns_empty_when_agents_dir_missing(self, temp_working_dir: Path) -> None:
        """Test returns empty dict when .claude/agents/ doesn't exist."""
        # Create mock for AgentDefinition
        mock_agent_def = MagicMock()
        mock_sdk = MagicMock()
        mock_sdk.AgentDefinition = mock_agent_def

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            result = load_agents_from_directory(str(temp_working_dir))
            assert result == {}

    def test_loads_valid_agent(self, temp_working_dir: Path, agents_dir: Path) -> None:
        """Test loading a valid agent from markdown file."""
        # Create agent file
        agent_content = """---
name: test-agent
description: A test agent for verification
model: sonnet
---

Test prompt content.
"""
        (agents_dir / "test-agent.md").write_text(agent_content)

        # Create mock for AgentDefinition
        mock_agent_def = MagicMock()
        mock_sdk = MagicMock()
        mock_sdk.AgentDefinition = mock_agent_def

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            result = load_agents_from_directory(str(temp_working_dir))

        assert "test-agent" in result
        # Verify AgentDefinition was called with correct args
        mock_agent_def.assert_called_once()
        call_kwargs = mock_agent_def.call_args[1]
        assert call_kwargs["description"] == "A test agent for verification"
        assert call_kwargs["prompt"] == "Test prompt content."
        assert call_kwargs["model"] == "sonnet"

    def test_skips_agent_without_description(
        self, temp_working_dir: Path, agents_dir: Path
    ) -> None:
        """Test agents without description are skipped."""
        agent_content = """---
name: no-desc
model: sonnet
---

Prompt content.
"""
        (agents_dir / "no-desc.md").write_text(agent_content)

        mock_agent_def = MagicMock()
        mock_sdk = MagicMock()
        mock_sdk.AgentDefinition = mock_agent_def

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            with patch("claude_task_master.core.subagents.console") as mock_console:
                result = load_agents_from_directory(str(temp_working_dir))

        assert result == {}
        # Should have logged a warning
        mock_console.warning.assert_called()

    def test_uses_filename_as_name_when_not_specified(
        self, temp_working_dir: Path, agents_dir: Path
    ) -> None:
        """Test agent name defaults to filename when not in frontmatter."""
        agent_content = """---
description: Agent without explicit name
---

Prompt.
"""
        (agents_dir / "my-cool-agent.md").write_text(agent_content)

        mock_agent_def = MagicMock()
        mock_sdk = MagicMock()
        mock_sdk.AgentDefinition = mock_agent_def

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            result = load_agents_from_directory(str(temp_working_dir))

        # Name should be filename stem
        assert "my-cool-agent" in result

    def test_invalid_model_uses_default(self, temp_working_dir: Path, agents_dir: Path) -> None:
        """Test invalid model specification falls back to default."""
        agent_content = """---
name: bad-model
description: Agent with invalid model
model: invalid-model
---

Prompt.
"""
        (agents_dir / "bad-model.md").write_text(agent_content)

        mock_agent_def = MagicMock()
        mock_sdk = MagicMock()
        mock_sdk.AgentDefinition = mock_agent_def

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            with patch("claude_task_master.core.subagents.console") as mock_console:
                result = load_agents_from_directory(str(temp_working_dir))

        assert "bad-model" in result
        # Model should be None (default)
        call_kwargs = mock_agent_def.call_args[1]
        assert call_kwargs["model"] is None
        mock_console.warning.assert_called()

    def test_valid_models_accepted(self, temp_working_dir: Path, agents_dir: Path) -> None:
        """Test all valid model types are accepted."""
        valid_models = ["opus", "sonnet", "haiku", "inherit"]

        for model in valid_models:
            agent_content = f"""---
name: {model}-agent
description: Agent with {model} model
model: {model}
---

Prompt.
"""
            (agents_dir / f"{model}-agent.md").write_text(agent_content)

        mock_agent_def = MagicMock()
        mock_sdk = MagicMock()
        mock_sdk.AgentDefinition = mock_agent_def

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            result = load_agents_from_directory(str(temp_working_dir))

        assert len(result) == len(valid_models)

    def test_loads_agent_with_tools(self, temp_working_dir: Path, agents_dir: Path) -> None:
        """Test loading agent with tools restriction."""
        agent_content = """---
name: restricted-agent
description: Agent with restricted tools
tools: [Read, Glob, Grep]
---

Prompt.
"""
        (agents_dir / "restricted-agent.md").write_text(agent_content)

        mock_agent_def = MagicMock()
        mock_sdk = MagicMock()
        mock_sdk.AgentDefinition = mock_agent_def

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            result = load_agents_from_directory(str(temp_working_dir))

        assert "restricted-agent" in result
        call_kwargs = mock_agent_def.call_args[1]
        assert call_kwargs["tools"] == ["Read", "Glob", "Grep"]

    def test_invalid_tools_set_to_none(self, temp_working_dir: Path, agents_dir: Path) -> None:
        """Test non-list tools specification is set to None."""
        agent_content = """---
name: bad-tools
description: Agent with invalid tools
tools: not-a-list
---

Prompt.
"""
        (agents_dir / "bad-tools.md").write_text(agent_content)

        mock_agent_def = MagicMock()
        mock_sdk = MagicMock()
        mock_sdk.AgentDefinition = mock_agent_def

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            result = load_agents_from_directory(str(temp_working_dir))

        assert "bad-tools" in result
        call_kwargs = mock_agent_def.call_args[1]
        assert call_kwargs["tools"] is None

    def test_loads_multiple_agents(self, temp_working_dir: Path, agents_dir: Path) -> None:
        """Test loading multiple agent files."""
        for i in range(3):
            agent_content = f"""---
name: agent-{i}
description: Agent number {i}
---

Prompt for agent {i}.
"""
            (agents_dir / f"agent-{i}.md").write_text(agent_content)

        mock_agent_def = MagicMock()
        mock_sdk = MagicMock()
        mock_sdk.AgentDefinition = mock_agent_def

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            result = load_agents_from_directory(str(temp_working_dir))

        assert len(result) == 3
        for i in range(3):
            assert f"agent-{i}" in result

    def test_handles_file_read_error(self, temp_working_dir: Path, agents_dir: Path) -> None:
        """Test graceful handling of file read errors."""
        # Create a valid agent
        valid_content = """---
name: valid-agent
description: A valid agent
---

Prompt.
"""
        (agents_dir / "valid.md").write_text(valid_content)

        # Create an unreadable file (we'll mock the read error)
        (agents_dir / "bad.md").write_text("dummy")

        mock_agent_def = MagicMock()
        mock_sdk = MagicMock()
        mock_sdk.AgentDefinition = mock_agent_def

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            with patch("claude_task_master.core.subagents.console") as mock_console:
                # Patch Path.read_text to raise for bad.md
                original_read = Path.read_text

                def mock_read_text(self, encoding=None):
                    if "bad.md" in str(self):
                        raise PermissionError("Cannot read file")
                    return original_read(self, encoding=encoding)

                with patch.object(Path, "read_text", mock_read_text):
                    result = load_agents_from_directory(str(temp_working_dir))

        # Valid agent should still be loaded
        assert "valid-agent" in result
        # Warning should be logged for bad file
        mock_console.warning.assert_called()

    def test_only_loads_md_files(self, temp_working_dir: Path, agents_dir: Path) -> None:
        """Test only .md files are loaded as agents."""
        # Create .md file
        md_content = """---
name: md-agent
description: Valid MD agent
---

Prompt.
"""
        (agents_dir / "agent.md").write_text(md_content)

        # Create non-.md files
        (agents_dir / "agent.txt").write_text("Not an agent")
        (agents_dir / "agent.yaml").write_text("name: not-agent")
        (agents_dir / "README").write_text("Readme content")

        mock_agent_def = MagicMock()
        mock_sdk = MagicMock()
        mock_sdk.AgentDefinition = mock_agent_def

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            result = load_agents_from_directory(str(temp_working_dir))

        assert len(result) == 1
        assert "md-agent" in result


# =============================================================================
# detect_claude_md Tests
# =============================================================================


class TestDetectClaudeMd:
    """Tests for detect_claude_md function."""

    def test_detects_uppercase_claude_md(self, temp_working_dir: Path) -> None:
        """Test detection of uppercase CLAUDE.md."""
        (temp_working_dir / "CLAUDE.md").write_text("# Project Instructions")

        with patch("claude_task_master.core.subagents.console") as mock_console:
            result = detect_claude_md(str(temp_working_dir))

        assert result is True
        mock_console.info.assert_called()

    def test_detects_lowercase_claude_md(self, temp_working_dir: Path) -> None:
        """Test detection of lowercase claude.md."""
        (temp_working_dir / "claude.md").write_text("# Project Instructions")

        with patch("claude_task_master.core.subagents.console") as mock_console:
            result = detect_claude_md(str(temp_working_dir))

        assert result is True
        mock_console.info.assert_called()

    def test_prefers_uppercase_over_lowercase(self, temp_working_dir: Path) -> None:
        """Test uppercase CLAUDE.md is detected when both exist."""
        (temp_working_dir / "CLAUDE.md").write_text("# Uppercase")
        (temp_working_dir / "claude.md").write_text("# Lowercase")

        with patch("claude_task_master.core.subagents.console") as mock_console:
            result = detect_claude_md(str(temp_working_dir))

        assert result is True
        # Should log info about CLAUDE.md (uppercase)
        call_args = mock_console.info.call_args[0][0]
        assert "CLAUDE.md" in call_args

    def test_returns_false_when_not_found(self, temp_working_dir: Path) -> None:
        """Test returns False when no CLAUDE.md exists."""
        with patch("claude_task_master.core.subagents.console") as mock_console:
            result = detect_claude_md(str(temp_working_dir))

        assert result is False
        mock_console.info.assert_not_called()

    def test_handles_nonexistent_directory(self) -> None:
        """Test handling of nonexistent working directory."""
        result = detect_claude_md("/nonexistent/path/to/dir")
        assert result is False


# =============================================================================
# detect_project_config Tests
# =============================================================================


class TestDetectProjectConfig:
    """Tests for detect_project_config function."""

    def test_empty_directory(self, temp_working_dir: Path) -> None:
        """Test detection in empty directory."""
        with patch("claude_task_master.core.subagents.console"):
            result = detect_project_config(str(temp_working_dir))

        assert result["claude_md"] is False
        assert result["agents"] == {}
        assert result["skills_dir"] is False

    def test_detects_claude_md(self, temp_working_dir: Path) -> None:
        """Test CLAUDE.md detection in config."""
        (temp_working_dir / "CLAUDE.md").write_text("# Instructions")

        with patch("claude_task_master.core.subagents.console"):
            result = detect_project_config(str(temp_working_dir))

        assert result["claude_md"] is True

    def test_detects_agents_directory(self, temp_working_dir: Path, agents_dir: Path) -> None:
        """Test agents directory detection."""
        (agents_dir / "test.md").write_text("---\nname: test\n---\nPrompt")

        with patch("claude_task_master.core.subagents.console") as mock_console:
            detect_project_config(str(temp_working_dir))

        # Should have logged about agents
        assert any("agent" in str(call).lower() for call in mock_console.info.call_args_list)

    def test_detects_skills_directory(self, temp_working_dir: Path) -> None:
        """Test skills directory detection."""
        skills_dir = temp_working_dir / ".claude" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "my-skill").mkdir()

        with patch("claude_task_master.core.subagents.console") as mock_console:
            result = detect_project_config(str(temp_working_dir))

        assert result["skills_dir"] is True
        assert any("skill" in str(call).lower() for call in mock_console.info.call_args_list)

    def test_detects_multiple_skills(self, temp_working_dir: Path) -> None:
        """Test detection of multiple skill directories."""
        skills_dir = temp_working_dir / ".claude" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "skill-1").mkdir()
        (skills_dir / "skill-2").mkdir()
        (skills_dir / "skill-3").mkdir()

        with patch("claude_task_master.core.subagents.console") as mock_console:
            result = detect_project_config(str(temp_working_dir))

        assert result["skills_dir"] is True
        # Check that 3 skills were logged
        assert any("3" in str(call) for call in mock_console.info.call_args_list)

    def test_empty_skills_directory(self, temp_working_dir: Path) -> None:
        """Test empty skills directory is not flagged."""
        skills_dir = temp_working_dir / ".claude" / "skills"
        skills_dir.mkdir(parents=True)
        # No subdirectories

        with patch("claude_task_master.core.subagents.console"):
            result = detect_project_config(str(temp_working_dir))

        assert result["skills_dir"] is False

    def test_full_configuration(self, temp_working_dir: Path, agents_dir: Path) -> None:
        """Test detection with full project configuration."""
        # Create CLAUDE.md
        (temp_working_dir / "CLAUDE.md").write_text("# Instructions")

        # Create agents
        (agents_dir / "agent1.md").write_text("---\nname: a1\ndesc: d\n---\nP")
        (agents_dir / "agent2.md").write_text("---\nname: a2\ndesc: d\n---\nP")

        # Create skills
        skills_dir = temp_working_dir / ".claude" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "my-skill").mkdir()

        with patch("claude_task_master.core.subagents.console"):
            result = detect_project_config(str(temp_working_dir))

        assert result["claude_md"] is True
        assert result["skills_dir"] is True


# =============================================================================
# get_agents_for_working_dir Tests
# =============================================================================


class TestGetAgentsForWorkingDir:
    """Tests for get_agents_for_working_dir function."""

    def test_calls_detect_project_config(self, temp_working_dir: Path) -> None:
        """Test that detect_project_config is called."""
        mock_agent_def = MagicMock()
        mock_sdk = MagicMock()
        mock_sdk.AgentDefinition = mock_agent_def

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            with patch("claude_task_master.core.subagents.detect_project_config") as mock_detect:
                mock_detect.return_value = {
                    "claude_md": False,
                    "agents": {},
                    "skills_dir": False,
                }
                get_agents_for_working_dir(str(temp_working_dir))

        mock_detect.assert_called_once_with(str(temp_working_dir))

    def test_returns_loaded_agents(self, temp_working_dir: Path, agents_dir: Path) -> None:
        """Test that loaded agents are returned."""
        agent_content = """---
name: test-agent
description: Test agent for verification
---

Prompt content.
"""
        (agents_dir / "test.md").write_text(agent_content)

        mock_agent_def = MagicMock()
        mock_sdk = MagicMock()
        mock_sdk.AgentDefinition = mock_agent_def

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            with patch("claude_task_master.core.subagents.console"):
                result = get_agents_for_working_dir(str(temp_working_dir))

        assert "test-agent" in result

    def test_returns_only_builtins_when_no_project_agents(self, temp_working_dir: Path) -> None:
        """Test only built-in agents are returned when the project defines none."""
        mock_agent_def = MagicMock()
        mock_sdk = MagicMock()
        mock_sdk.AgentDefinition = mock_agent_def

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            with patch("claude_task_master.core.subagents.console"):
                result = get_agents_for_working_dir(str(temp_working_dir))

        assert set(result) == set(BUILTIN_AGENT_NAMES)

    def test_integration_with_full_setup(self, temp_working_dir: Path, agents_dir: Path) -> None:
        """Test full integration with CLAUDE.md and agents."""
        # Setup CLAUDE.md
        (temp_working_dir / "CLAUDE.md").write_text("# Project Instructions")

        # Setup agents
        for i in range(2):
            content = f"""---
name: agent-{i}
description: Agent number {i}
model: sonnet
---

Prompt {i}.
"""
            (agents_dir / f"agent-{i}.md").write_text(content)

        mock_agent_def = MagicMock()
        mock_sdk = MagicMock()
        mock_sdk.AgentDefinition = mock_agent_def

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            with patch("claude_task_master.core.subagents.console"):
                result = get_agents_for_working_dir(str(temp_working_dir))

        assert len(result) == 2 + len(BUILTIN_AGENT_NAMES)
        assert "agent-0" in result
        assert "agent-1" in result
        assert HIVE_WORKER_AGENT_NAME in result


# =============================================================================
# Built-in agents (hive-worker)
# =============================================================================


class TestBuiltinAgents:
    """Tests for the programmatic built-in agent definitions."""

    def test_returns_empty_when_sdk_missing(self) -> None:
        """Built-ins degrade to {} rather than crashing without the SDK."""
        with patch.dict("sys.modules", {"claude_agent_sdk": None}):
            assert build_builtin_agents() == {}

    def test_get_agents_survives_missing_sdk(self, temp_working_dir: Path) -> None:
        """The whole entry point still returns {} without the SDK."""
        with patch.dict("sys.modules", {"claude_agent_sdk": None}):
            with patch("claude_task_master.core.subagents.console"):
                result = get_agents_for_working_dir(str(temp_working_dir))

        assert result == {}

    def test_hive_worker_is_built_in(self) -> None:
        """hive-worker needs no file in the target project."""
        agents = build_builtin_agents()

        assert HIVE_WORKER_AGENT_NAME in agents
        assert HIVE_WORKER_AGENT_NAME in BUILTIN_AGENT_NAMES

    def test_hive_worker_inherits_model(self) -> None:
        """A worker runs on the lead's model, not a fixed tier."""
        agent = build_builtin_agents()[HIVE_WORKER_AGENT_NAME]

        assert agent.model == "inherit"

    def test_hive_worker_has_all_tools(self) -> None:
        """tools=None means unrestricted: it needs Read/Edit/Write/Bash/Grep/Glob."""
        agent = build_builtin_agents()[HIVE_WORKER_AGENT_NAME]

        assert agent.tools is None

    def test_hive_worker_description_says_when_to_use_it(self) -> None:
        """Claude picks agents by description; it must name the trigger.

        The trigger is ONE PIECE of the lead's single task — not a task of its
        own, and not a batch of them.
        """
        description = HIVE_WORKER_DESCRIPTION.lower()

        assert "one piece of the task" in description
        assert "exclusive" in description
        assert "disjoint" in description
        assert "parallel" in description

    def test_hive_worker_prompt_forbids_files_outside_its_set(self) -> None:
        """Contract point 1 + 2: exclusive file set, collisions are reported."""
        prompt = HIVE_WORKER_PROMPT.lower()

        assert "exclusive" in prompt
        assert "collision" in prompt
        assert "stop" in prompt

    def test_hive_worker_prompt_forbids_git(self) -> None:
        """Contract point 3: the lead is the only thing that touches git."""
        prompt = HIVE_WORKER_PROMPT.lower()

        assert "no git commands" in prompt
        for command in ("git add", "commit", "branch", "checkout", "stash", "push"):
            assert command in prompt
        assert "uncommitted" in prompt

    def test_hive_worker_prompt_limits_verification(self) -> None:
        """Contract point 4: narrow checks only, never the full suite."""
        prompt = HIVE_WORKER_PROMPT.lower()

        assert "full test suite" in prompt
        assert "-n auto" in prompt

    def test_hive_worker_prompt_requires_a_report(self) -> None:
        """Contract point 5 + 6: the final message is the only channel."""
        prompt = HIVE_WORKER_PROMPT.lower()

        assert "final message" in prompt
        assert "verified" in prompt
        assert "no channel to a human" in prompt

    def test_hive_worker_prompt_forbids_worktrees_and_private_copies(self) -> None:
        """One shared checkout: the work must land in the tree the lead commits.

        A worker that "isolates itself" in a worktree or a copy produces a clean
        tree here and a lost change there — the failure looks like the agent
        having done nothing at all.
        """
        prompt = HIVE_WORKER_PROMPT.lower()

        assert "never create a git worktree" in prompt
        assert "never clone" in prompt
        assert "directory of your own" in prompt

    def test_hive_worker_prompt_forbids_the_leads_sign_off(self) -> None:
        """`TASK COMPLETE` is the lead's, emitted after the commit.

        Defence in depth for the subagent isolation in agent_message.py: even if
        a worker's narration reached the lead's result_text, the worker is told
        never to write the sentinel that signs the whole session off.
        """
        prompt = HIVE_WORKER_PROMPT

        assert "TASK COMPLETE" in prompt
        lowered = prompt.lower()
        assert "never write" in lowered
        assert "lead" in lowered

    def test_builtins_merged_with_project_agents(
        self, temp_working_dir: Path, agents_dir: Path
    ) -> None:
        """Project agents and built-ins coexist."""
        (agents_dir / "custom.md").write_text(
            "---\nname: custom-agent\ndescription: A project agent\n---\n\nProject prompt.\n"
        )

        with patch("claude_task_master.core.subagents.console"):
            result = get_agents_for_working_dir(str(temp_working_dir))

        assert "custom-agent" in result
        assert HIVE_WORKER_AGENT_NAME in result

    def test_project_agent_overrides_builtin(
        self, temp_working_dir: Path, agents_dir: Path
    ) -> None:
        """A user override of the same name must beat our built-in."""
        (agents_dir / "hive-worker.md").write_text(
            f"---\nname: {HIVE_WORKER_AGENT_NAME}\n"
            "description: My own worker contract\nmodel: haiku\n---\n\nMy prompt.\n"
        )

        with patch("claude_task_master.core.subagents.console"):
            result = get_agents_for_working_dir(str(temp_working_dir))

        agent = result[HIVE_WORKER_AGENT_NAME]
        assert agent.description == "My own worker contract"
        assert agent.prompt == "My prompt."
        assert agent.model == "haiku"

    def test_builtins_are_rebuilt_per_call(self) -> None:
        """Mutating one call's result must not poison the next."""
        first = build_builtin_agents()
        first.pop(HIVE_WORKER_AGENT_NAME)

        assert HIVE_WORKER_AGENT_NAME in build_builtin_agents()


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_frontmatter_with_special_characters(self) -> None:
        """Test frontmatter with special characters in values."""
        content = """---
name: special-agent
description: Agent with special chars: @#$%^&*()
---

Prompt.
"""
        frontmatter, prompt = parse_agent_frontmatter(content)

        assert frontmatter["name"] == "special-agent"
        assert "@#$%^&*()" in frontmatter["description"]

    def test_frontmatter_with_unicode(self) -> None:
        """Test frontmatter with unicode characters."""
        content = """---
name: unicode-agent
description: 日本語テスト émojis 🚀
---

日本語プロンプト
"""
        frontmatter, prompt = parse_agent_frontmatter(content)

        assert frontmatter["name"] == "unicode-agent"
        assert "日本語" in frontmatter["description"]
        assert "🚀" in frontmatter["description"]
        assert "日本語プロンプト" in prompt

    def test_empty_list_in_frontmatter(self) -> None:
        """Test empty list parsing in frontmatter."""
        content = """---
tools: []
---

Prompt.
"""
        frontmatter, prompt = parse_agent_frontmatter(content)

        assert frontmatter["tools"] == []

    def test_frontmatter_without_newline_after_closing(self) -> None:
        """Test frontmatter without newline after closing marker."""
        content = """---
name: test
---
Prompt immediately after."""
        frontmatter, prompt = parse_agent_frontmatter(content)

        assert frontmatter["name"] == "test"
        assert prompt == "Prompt immediately after."

    def test_very_long_prompt(self) -> None:
        """Test handling of very long prompt content."""
        long_prompt = "A" * 100000  # 100K characters
        content = f"""---
name: long-prompt-agent
description: Agent with long prompt
---

{long_prompt}
"""
        frontmatter, prompt = parse_agent_frontmatter(content)

        assert frontmatter["name"] == "long-prompt-agent"
        assert len(prompt) == len(long_prompt)

    def test_multiple_dashes_in_content(self) -> None:
        """Test content with multiple dash sequences."""
        content = """---
name: dash-test
---

Here is some content with ---dashes--- in it.
And more --- like --- this.
"""
        frontmatter, prompt = parse_agent_frontmatter(content)

        assert frontmatter["name"] == "dash-test"
        assert "---dashes---" in prompt

    def test_numeric_values_in_frontmatter(self) -> None:
        """Test numeric values remain as strings (simple YAML parser)."""
        content = """---
name: numeric-test
count: 42
version: 1.5
---

Prompt.
"""
        frontmatter, prompt = parse_agent_frontmatter(content)

        # Values should be strings (no numeric parsing in simple YAML)
        assert frontmatter["count"] == "42"
        assert frontmatter["version"] == "1.5"


class TestListProjectAgents:
    """The lead's fan-out brief needs (name, description) without SDK or I/O noise."""

    def test_returns_name_description_pairs(self, temp_working_dir: Path, agents_dir: Path) -> None:
        from claude_task_master.core.subagents import list_project_agents

        (agents_dir / "reviewer.md").write_text(
            "---\nname: code-reviewer\ndescription: Reviews diffs for defects\n---\n\nPrompt.\n"
        )
        (agents_dir / "adder.md").write_text(
            "---\nname: add-primitive\ndescription: Adds a new framework primitive\n---\n\nPrompt.\n"
        )

        pairs = list_project_agents(str(temp_working_dir))

        assert pairs == [
            ("add-primitive", "Adds a new framework primitive"),
            ("code-reviewer", "Reviews diffs for defects"),
        ]

    def test_skips_agents_without_description(
        self, temp_working_dir: Path, agents_dir: Path
    ) -> None:
        """Load-time skips them too — the brief must match what is invocable."""
        from claude_task_master.core.subagents import list_project_agents

        (agents_dir / "mute.md").write_text("---\nname: mute\n---\n\nPrompt.\n")

        assert list_project_agents(str(temp_working_dir)) == []

    def test_missing_directory_is_empty(self, temp_working_dir: Path) -> None:
        from claude_task_master.core.subagents import list_project_agents

        assert list_project_agents(str(temp_working_dir)) == []

    def test_falls_back_to_filename_and_collapses_whitespace(
        self, temp_working_dir: Path, agents_dir: Path
    ) -> None:
        from claude_task_master.core.subagents import list_project_agents

        (agents_dir / "helper.md").write_text("---\ndescription: Does   the\tthing\n---\n\nP.\n")

        assert list_project_agents(str(temp_working_dir)) == [("helper", "Does the thing")]


class TestHiveWorkerTurnBudget:
    """Workers carry big pieces, so each gets its own maxTurns budget."""

    def test_default_budget_applied(self) -> None:
        from claude_task_master.core.hive import DEFAULT_HIVE_WORKER_MAX_TURNS
        from claude_task_master.core.subagents import build_builtin_agents

        agents = build_builtin_agents()
        assert agents["hive-worker"].maxTurns == DEFAULT_HIVE_WORKER_MAX_TURNS

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from claude_task_master.core.subagents import build_builtin_agents

        monkeypatch.setenv("CLAUDETM_HIVE_WORKER_MAX_TURNS", "500")
        assert build_builtin_agents()["hive-worker"].maxTurns == 500

    def test_garbage_env_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from claude_task_master.core.hive import DEFAULT_HIVE_WORKER_MAX_TURNS
        from claude_task_master.core.subagents import build_builtin_agents

        monkeypatch.setenv("CLAUDETM_HIVE_WORKER_MAX_TURNS", "lots")
        assert build_builtin_agents()["hive-worker"].maxTurns == DEFAULT_HIVE_WORKER_MAX_TURNS


class TestProjectAgentMaxTurns:
    """A project agent may pin its own turn budget in frontmatter."""

    def test_max_turns_parsed(self, temp_working_dir: Path, agents_dir: Path) -> None:
        from claude_task_master.core.subagents import load_agents_from_directory

        (agents_dir / "big.md").write_text(
            "---\nname: big\ndescription: Big worker\nmax_turns: 300\n---\n\nP.\n"
        )

        agents = load_agents_from_directory(str(temp_working_dir))
        assert agents["big"].maxTurns == 300

    def test_invalid_max_turns_ignored(self, temp_working_dir: Path, agents_dir: Path) -> None:
        from claude_task_master.core.hive import hive_worker_max_turns
        from claude_task_master.core.subagents import load_agents_from_directory

        (agents_dir / "odd.md").write_text(
            "---\nname: odd\ndescription: Odd worker\nmax_turns: banana\n---\n\nP.\n"
        )

        with patch("claude_task_master.core.subagents.console"):
            agents = load_agents_from_directory(str(temp_working_dir))
        # Falls back to the shared worker budget, never to unbounded: the lead
        # is told to prefer project specialists, so an unbounded one could spend
        # the session's whole aggregate turn budget by itself.
        assert agents["odd"].maxTurns == hive_worker_max_turns()


class TestHiveWorkerBigPieceContract:
    """Workers are meant to carry big self-contained pieces, finished completely."""

    def test_prompt_tells_the_worker_to_own_a_big_piece(self) -> None:
        prompt = HIVE_WORKER_PROMPT.lower()
        assert "own it end to end" in prompt
        assert "completely" in prompt

    def test_prompt_forbids_spawning_further_agents(self) -> None:
        prompt = HIVE_WORKER_PROMPT.lower()
        assert "never spawn agents of your own" in prompt

    def test_description_says_the_piece_can_be_large(self) -> None:
        assert "large" in HIVE_WORKER_DESCRIPTION.lower()
