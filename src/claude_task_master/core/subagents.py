"""Subagent Loader - Load subagents from .claude/agents/ directory.

This module loads AgentDefinition configurations from markdown files in
the project's .claude/agents/ directory, similar to how developerz.ai does it.

Agent files use YAML frontmatter format:
---
name: agent-name
description: When to use this agent...
model: opus|sonnet|haiku
---

Agent prompt content here...

It also ships built-in definitions (see :data:`BUILTIN_AGENT_NAMES`) that need no
file in the target project — notably ``hive-worker``, the worker contract for
``--parallel-tasks`` fan-out. A project file of the same name always wins.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import console

if TYPE_CHECKING:
    pass


def parse_agent_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from agent markdown file.

    Args:
        content: Full content of the markdown file.

    Returns:
        Tuple of (frontmatter_dict, prompt_content).
    """
    # Match YAML frontmatter between --- markers
    frontmatter_pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
    match = re.match(frontmatter_pattern, content, re.DOTALL)

    if not match:
        # No frontmatter, treat entire content as prompt
        return {}, content.strip()

    frontmatter_str = match.group(1)
    prompt = match.group(2).strip()

    # Parse simple YAML (key: value pairs)
    frontmatter: dict[str, Any] = {}
    for line in frontmatter_str.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()

            # Handle special values
            if value.lower() in ("true", "yes"):
                value = True
            elif value.lower() in ("false", "no"):
                value = False
            elif value.startswith("[") and value.endswith("]"):
                # Simple list parsing: [item1, item2]
                value = [v.strip().strip("\"'") for v in value[1:-1].split(",")]

            frontmatter[key] = value

    return frontmatter, prompt


def load_agents_from_directory(working_dir: str) -> dict[str, Any]:
    """Load all agent definitions from .claude/agents/ directory.

    Reads markdown files from {working_dir}/.claude/agents/ and converts
    them to AgentDefinition objects.

    Args:
        working_dir: The project working directory.

    Returns:
        Dictionary of agent_name -> AgentDefinition.
    """
    try:
        from claude_agent_sdk import AgentDefinition
    except ImportError:
        console.warning("claude_agent_sdk not installed - skipping subagent loading")
        return {}

    agents_dir = Path(working_dir) / ".claude" / "agents"

    if not agents_dir.exists():
        return {}

    agents: dict[str, Any] = {}

    for agent_file in agents_dir.glob("*.md"):
        try:
            content = agent_file.read_text(encoding="utf-8")
            frontmatter, prompt = parse_agent_frontmatter(content)

            # Get agent name from frontmatter or filename
            name = frontmatter.get("name") or agent_file.stem

            # Get description (required for Claude to know when to use it)
            description = frontmatter.get("description", "")
            if not description:
                console.warning(f"Agent '{name}' has no description - skipping")
                continue

            # Get optional model override
            model = frontmatter.get("model")
            if model and model not in ("opus", "sonnet", "haiku", "inherit"):
                console.warning(f"Agent '{name}' has invalid model '{model}' - using default")
                model = None

            # Get optional tools restriction
            tools = frontmatter.get("tools")
            if tools and not isinstance(tools, list):
                tools = None

            # Create AgentDefinition
            agent_def = AgentDefinition(
                description=description,
                prompt=prompt,
                model=model,
                tools=tools,
            )

            agents[name] = agent_def

        except Exception as e:
            console.warning(f"Failed to load agent from {agent_file}: {e}")
            continue

    return agents


HIVE_WORKER_AGENT_NAME = "hive-worker"

HIVE_WORKER_DESCRIPTION = (
    "Implements exactly ONE task from the current PR group, confined to an exclusive, "
    "disjoint set of files that you name in the brief. Use this when you are the hive "
    "lead running a batch of tasks for one PR and you have found two or more tasks whose "
    "write sets do not overlap: hand each one to its own hive-worker, in parallel, in this "
    "same checkout. Each worker must be given its task and the exact list of files it "
    "exclusively owns. Do NOT use it for anything touching git, for two tasks that write "
    "the same file, or for a single small edit you can finish yourself faster than the "
    "fan-out costs."
)

HIVE_WORKER_PROMPT = """You are a hive worker. You implement ONE task from the current PR
group, in the shared checkout you were started in, alongside other workers running at the
same time. Your brief names your task and the exclusive set of files you own.

## Your file set is exclusive — and it is a hard boundary
- You may create, edit and delete ONLY the files in your set. Reading anything in the repo
  is fine and encouraged; writing outside your set is not, ever.
- Another worker is editing the files you do not own, right now. Writing one of them
  silently destroys their work or yours — the last writer wins and nobody is told.
- If your task turns out to need a file you do not own: STOP and report the collision.
  Do not edit it "just a little", do not create a variant of it, and do not try to
  coordinate with another worker — you have no channel to them, and they cannot see you.
  Say which file you need and why; the lead resolves it.

## Run NO git commands. None.
- No `git add`, `commit`, `branch`, `checkout`, `switch`, `stash`, `push`, `pull`, `rebase`,
  `merge`, `reset`, `restore`, `clean`, `worktree` — not even "harmless" ones. `git status`
  and `git diff` are shared, mutable state under concurrent workers, and anything that
  stages or moves HEAD corrupts every other worker in the checkout at once.
- Leave your work uncommitted in the working tree. The lead commits and pushes for the
  whole batch, once, after every worker has reported.

## Verify narrowly
- Run only the checks that cover the files you touched — the specific test file(s), a
  targeted lint of your own paths, a type check if it is cheap and scoped.
- Never run the full test suite, never `-n auto` or any other parallelism flag, never a
  whole-repo build. Other workers are running their own checks on the same machine, and
  the lead runs the full gate once at the end. A full suite here is contention, and its
  failures are usually another worker's half-finished work, not yours.

## Report back — your final message is all the lead sees
The lead cannot see your tool calls, your reasoning, or your diffs. Only the text you
finish with. It must state, concretely:
1. Every file you changed (exact paths), and whether created, edited or deleted.
2. What you did — the actual change, not a restatement of the task.
3. What you verified: the exact commands you ran and their outcome.
4. Any collision you hit, any assumption you made, anything you left undone.

Never write the words `TASKS COMPLETE` anywhere in your report, in any form: that label is
the lead's own manifest of what the batch finished, and a copy of it in your text can check
off plan tasks nobody did. Say "done" in prose instead.

## You have no channel to a human
Nobody will answer a question you ask. When the task is underspecified you have exactly two
moves: decide, do the work, and flag the assumption explicitly in your report — or stop,
change nothing, and report what blocked you with the evidence for it. Never end by asking
for input, and never report success for work you did not verify."""


def build_builtin_agents() -> dict[str, Any]:
    """Build the agent definitions claudetm ships itself.

    These need no file in the target project. They are merged *under* the
    project's ``.claude/agents/`` definitions, so a user file of the same name
    overrides ours.

    Returns:
        Dictionary of agent_name -> AgentDefinition, or ``{}`` if the SDK is
        not installed.
    """
    try:
        from claude_agent_sdk import AgentDefinition
    except ImportError:
        # Same degradation as load_agents_from_directory: no SDK, no agents.
        return {}

    return {
        HIVE_WORKER_AGENT_NAME: AgentDefinition(
            description=HIVE_WORKER_DESCRIPTION,
            prompt=HIVE_WORKER_PROMPT,
            model="inherit",
            tools=None,
        )
    }


BUILTIN_AGENT_NAMES: tuple[str, ...] = (HIVE_WORKER_AGENT_NAME,)


def detect_claude_md(working_dir: str) -> bool:
    """Detect and log if CLAUDE.md exists in the working directory.

    Args:
        working_dir: The project working directory.

    Returns:
        True if CLAUDE.md was found, False otherwise.
    """
    claude_md_path = Path(working_dir) / "CLAUDE.md"

    if claude_md_path.exists():
        console.info(f"Found project instructions: {claude_md_path}")
        return True

    # Also check for lowercase variant
    claude_md_lower = Path(working_dir) / "claude.md"
    if claude_md_lower.exists():
        console.info(f"Found project instructions: {claude_md_lower}")
        return True

    return False


def detect_project_config(working_dir: str) -> dict[str, Any]:
    """Detect all Claude project configuration in the working directory.

    Logs what was found for visibility.

    Args:
        working_dir: The project working directory.

    Returns:
        Dictionary with detected configuration info.
    """
    result: dict[str, Any] = {
        "claude_md": False,
        "agents": {},
        "skills_dir": False,
    }

    # Detect CLAUDE.md
    result["claude_md"] = detect_claude_md(working_dir)

    # Detect .claude directory
    claude_dir = Path(working_dir) / ".claude"
    if claude_dir.exists():
        # Check for agents
        agents_dir = claude_dir / "agents"
        if agents_dir.exists():
            agent_files = list(agents_dir.glob("*.md"))
            if agent_files:
                agent_names = [f.stem for f in agent_files]
                console.info(f"Found {len(agent_files)} subagent(s): {', '.join(agent_names)}")

        # Check for skills
        skills_dir = claude_dir / "skills"
        if skills_dir.exists():
            skill_dirs = [d for d in skills_dir.iterdir() if d.is_dir()]
            if skill_dirs:
                skill_names = [d.name for d in skill_dirs]
                console.info(f"Found {len(skill_dirs)} skill(s): {', '.join(skill_names)}")
                result["skills_dir"] = True

    return result


def get_agents_for_working_dir(working_dir: str) -> dict[str, Any]:
    """Get all available agents for a working directory.

    This is the main entry point for loading subagents.
    Also detects and logs CLAUDE.md and other project config.

    Built-in definitions (``hive-worker``) are merged with the project's
    ``.claude/agents/`` files; a project file of the same name wins, so a user
    override always beats ours. An unused definition is harmless — Claude only
    invokes an agent when the prompt asks for it.

    Args:
        working_dir: The project working directory.

    Returns:
        Dictionary of agent_name -> AgentDefinition.
    """
    # Detect and log project configuration
    detect_project_config(working_dir)

    # Built-ins first, so project files of the same name overwrite them.
    agents = build_builtin_agents()
    agents.update(load_agents_from_directory(working_dir))
    return agents
