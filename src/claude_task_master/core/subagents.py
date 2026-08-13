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
file in the target project — notably ``hive-worker``, the worker contract a work
session's lead agent uses when it splits its one task into disjoint pieces
(``TaskOptions.parallel``). A project file of the same name always wins.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import console
from .hive import hive_worker_effort, hive_worker_max_turns

if TYPE_CHECKING:
    pass


#: Frontmatter keys whose value is always text, never a YAML boolean. Without
#: this, `description: no` parsed to False and the agent was dropped as
#: description-less, and a quoted `name: "my-agent"` registered under a name the
#: lead could never dispatch.
_TEXT_KEYS: frozenset[str] = frozenset({"name", "description", "model"})


def _coerce(key: str, value: str) -> Any:
    """Turn one frontmatter scalar into a Python value."""
    if value[:1] in ("'", '"') and value[-1:] == value[:1] and len(value) >= 2:
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        return [v.strip().strip("\"'") for v in value[1:-1].split(",") if v.strip()]
    if key not in _TEXT_KEYS:
        lowered = value.lower()
        if lowered in ("true", "yes"):
            return True
        if lowered in ("false", "no"):
            return False
    return value


def parse_agent_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from an agent markdown file.

    A deliberately small subset of YAML, but it has to cover what Claude Code's
    own agent files actually contain, which the original key/value split did
    not. Each of these silently produced a broken agent:

    - a **folded or literal description** (``description: >`` followed by
      indented lines) became the single character ``>``, so the specialist was
      advertised to the lead as ``>`` and never matched — every piece fell back
      to a generic worker;
    - a **quoted name** registered the agent under ``"my-agent"`` while the lead
      dispatched ``my-agent``, so the dispatch failed and its turns were lost;
    - a **block list** (``tools:`` followed by ``- Read``) became ``""``, which
      is falsy-but-not-None and reached the SDK as an empty tool set;
    - **nested keys** under any parent (``metadata:`` then an indented
      ``name:``) overwrote the real top-level value;
    - a file whose final ``---`` had no trailing newline failed the regex
      outright and became a prompt with no frontmatter at all.

    Args:
        content: Full content of the markdown file.

    Returns:
        Tuple of (frontmatter_dict, prompt_content).
    """
    # Tolerate a missing trailing newline after the closing delimiter.
    frontmatter_pattern = r"^---\s*\n(.*?)\n---\s*(?:\n(.*))?$"
    match = re.match(frontmatter_pattern, content, re.DOTALL)

    if not match:
        # No frontmatter, treat entire content as prompt
        return {}, content.strip()

    frontmatter_str = match.group(1)
    prompt = (match.group(2) or "").strip()

    frontmatter: dict[str, Any] = {}
    pending_key: str | None = None  # key awaiting a block list or folded scalar
    pending_list: list[str] = []
    pending_text: list[str] = []

    def flush() -> None:
        nonlocal pending_key, pending_list, pending_text
        if pending_key is not None:
            if pending_list:
                frontmatter[pending_key] = pending_list
            elif pending_text:
                frontmatter[pending_key] = " ".join(pending_text)
        pending_key, pending_list, pending_text = None, [], []

    for raw_line in frontmatter_str.split("\n"):
        if not raw_line.strip() or raw_line.strip().startswith("#"):
            continue
        indented = raw_line[:1].isspace()
        stripped = raw_line.strip()

        # Continuation of a block list / folded scalar opened on a previous line.
        if pending_key is not None and (indented or stripped.startswith("- ")):
            if stripped.startswith("- "):
                pending_list.append(stripped[2:].strip().strip("\"'"))
            else:
                pending_text.append(stripped)
            continue

        # An indented key with nothing pending belongs to some nested mapping we
        # do not model. Skipping it is the point: it must not clobber a
        # top-level key of the same name.
        if indented:
            continue

        flush()

        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()

        if value in ("", ">", "|", ">-", "|-", ">+", "|+"):
            # Opens a block list or a multi-line scalar; its body follows.
            pending_key = key
            continue

        frontmatter[key] = _coerce(key, value)

    flush()

    return frontmatter, prompt


def load_agents_from_directory(working_dir: str) -> dict[str, Any]:
    """Load all agent definitions from .claude/agents/ directory.

    Reads markdown files from {working_dir}/.claude/agents/ and converts
    them to AgentDefinition objects.

    .. note::
       **Not on the query path.** ``get_agents_for_working_dir`` no longer calls
       this: the CLI loads the project's agent files itself, and passing them
       again registered every one twice. Kept as the executable statement of the
       frontmatter contract (and exercised by its tests), so changing the parser
       here changes what :func:`list_project_agents` advertises to the lead —
       but the ``AgentDefinition`` fields it builds no longer reach the SDK.

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

            # Optional per-agent turn budget (max_turns / maxTurns frontmatter).
            # Defaults to the hive worker's budget rather than to unbounded: the
            # lead is told to prefer these specialists over hive-worker, so an
            # unbounded one could spend the session's whole aggregate turn
            # budget alone — the exact runaway the worker budget exists to stop.
            raw_turns = frontmatter.get("max_turns", frontmatter.get("maxTurns"))
            max_turns: int | None = hive_worker_max_turns()
            if raw_turns is not None and not isinstance(raw_turns, bool):
                try:
                    parsed_turns = int(raw_turns)
                except (TypeError, ValueError):
                    console.warning(
                        f"Agent '{name}' has invalid max_turns '{raw_turns}' - ignoring"
                    )
                else:
                    if parsed_turns > 0:
                        max_turns = parsed_turns

            # Optional per-agent background flag. Defaults to foreground for the
            # same reason hive-worker does: claudetm dispatches these as workers
            # in the lead's own checkout, and one still writing after the lead
            # ends its turn costs the whole task. A project that really wants a
            # detached agent says `background: true` explicitly.
            raw_background = frontmatter.get("background")
            background = raw_background if isinstance(raw_background, bool) else False

            # Create AgentDefinition
            agent_def = AgentDefinition(
                description=description,
                prompt=prompt,
                model=model,
                tools=tools,
                maxTurns=max_turns,
                background=background,
            )

            agents[name] = agent_def

        except Exception as e:
            console.warning(f"Failed to load agent from {agent_file}: {e}")
            continue

    return agents


HIVE_WORKER_AGENT_NAME = "hive-worker"

HIVE_WORKER_DESCRIPTION = (
    "Implements ONE piece of the task the lead is working on, confined to an exclusive, "
    "disjoint set of files that you name in the brief. The piece can be LARGE — a whole "
    "module or feature slice with its tests, implemented end to end. Use this when you are "
    "the lead of a work session and your task splits into two or more pieces whose write "
    "sets do not overlap: hand each piece to its own hive-worker, in parallel, in this same "
    "checkout. Each worker must be given its piece in full and the exact list of files it "
    "exclusively owns. Do NOT use it for anything touching git, for two pieces that write "
    "the same file, or for a small edit you can finish yourself faster than the fan-out costs."
)

HIVE_WORKER_PROMPT = """You are a hive worker. You implement ONE piece of the task your lead
is working on, in the shared checkout you were started in, alongside other workers running
at the same time. Your brief names your piece and the exclusive set of files you own.

You are a team working in one directory, at the same time, on one task — that is the whole
point, and it is what makes you fast. It also means there is exactly one copy of everything:
no branch of your own, no sandbox, no undo. Every rule below follows from that single fact,
and each one is what lets the others work in parallel with you instead of on top of you.

## Your piece can be big — own it end to end
A piece is often a whole module, a feature slice, a subsystem sweep. Plan it briefly before
editing, then implement it COMPLETELY inside your file set: the code, its tests, its docs.
Never return half-done work or leave "the rest" for the lead — the piece was cut so you take
it off the lead's plate entirely. You have your own turn budget sized for real work; use it.
Never spawn agents of your own: the lead sized the team, and a worker's worker is invisible
concurrency the exclusive file sets do not cover.

## Your file set is exclusive — and it is a hard boundary
- You may create, edit and delete ONLY the files in your set. Reading anything in the repo
  is fine and encouraged; writing outside your set is not, ever.
- Another worker is editing the files you do not own, right now. Writing one of them
  silently destroys their work or yours — the last writer wins and nobody is told.
- If your piece turns out to need a file you do not own: STOP and report the collision.
  Do not edit it "just a little", do not create a variant of it, and do not try to
  coordinate with another worker — you have no channel to them, and they cannot see you.
  Say which file you need and why; the lead resolves it.

## Run NO git commands. None.
- No `git add`, `commit`, `branch`, `checkout`, `switch`, `stash`, `push`, `pull`, `rebase`,
  `merge`, `reset`, `restore`, `clean`, `worktree` — not even "harmless" ones. `git status`
  and `git diff` are shared, mutable state under concurrent workers, and anything that
  stages or moves HEAD corrupts every other worker in the checkout at once.
- Work directly in this checkout. Never create a git worktree, never clone, never copy the
  project into a directory of your own — your changes have to land in the tree the lead
  commits from, and the file set above is the only lock there is.
- Leave your work uncommitted in the working tree. The lead commits and pushes for the
  whole task, once, after every worker has reported.

## A command that writes counts as writing — most boundary breaks arrive this way
The rule above is about files changing, not about which tool changed them. You will not think
of these as edits, and they are:
- **A formatter or autofixer pointed at the repo** rewrites every worker's files at once,
  including the half-finished file another worker is editing right now. Scope it to your own
  paths, by explicit path, every time.
- **A build or codegen step that emits artifacts** has several workers racing over the same
  generated output. Use the check-only / no-emit form when the tool has one.
- **Anything that regenerates something shared** — a lockfile, committed snapshots, a schema.
If your check has no scoped form, skip it and say so in your report. The lead runs the full
gate once at the end; a check you cannot run narrowly is the lead's job, not yours.

## Verify narrowly — and only what your brief allows
- **Your brief names the checks you may run. Follow it exactly.** Whether this project can
  stand several test or lint runs at once is something only the lead can see (shared database,
  fixed port, one build directory, a lock), so it decided and told you. If the brief says to
  run nothing, run nothing and say so in your report — the lead runs the full gate at the end.
- Where you are allowed to check, cover only the files you touched — the specific test
  file(s), a targeted lint of your own paths, a type check if it is cheap and scoped.
- Never run the full test suite, never `-n auto` or any other parallelism flag, never a
  whole-repo build. Other workers are running their own checks on the same machine, and
  the lead runs the full gate once at the end. A full suite here is contention, and its
  failures are usually another worker's half-finished work, not yours.
- A failure in a file you do not own is not yours to fix. Report it; do not reach across
  the boundary to "just make the build green".

## Report back — your final message is all the lead sees
The lead cannot see your tool calls, your reasoning, or your diffs. Only the text you
finish with. It must state, concretely:
1. Every file you changed (exact paths), and whether created, edited or deleted.
2. What you did — the actual change, not a restatement of the brief.
3. What you verified: the exact commands you ran and their outcome.
4. Any collision you hit, any assumption you made, anything you left undone.

Never write the words `TASK COMPLETE` anywhere in your report, in any form: that is the
lead's own sign-off for the whole task, emitted only after every worker has returned and
the work is committed. Your piece finishing is not that. Say "done" in prose instead.

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
            # A worker's worker is concurrency nobody sized and the exclusive
            # file sets do not cover. The contract has always forbidden it in
            # prose; this makes it structural, because the cost of it happening
            # is unbounded — recursive fan-out multiplies past `max_parallel`
            # and past the session's shared turn and cost budget.
            disallowedTools=["Task", "Agent"],
            # Workers carry big pieces, so the budget is generous — but it is
            # theirs alone: one runaway worker must not burn the session's
            # aggregate limits on everyone else's behalf.
            maxTurns=hive_worker_max_turns(),
            # Foreground, mechanically. The brief has always said to pass
            # `run_in_background: false` on every worker, and leads ignore it
            # about a quarter of the time (measured across real runs: 39 of 210
            # dispatches explicitly backgrounded, 18 more omitting the parameter,
            # which the Agent tool defaults to background). The cost of each miss
            # is the whole task: the worker keeps writing after the lead ends its
            # turn, the orchestrator finds a dirty tree, reads the session as
            # unfinished and re-runs everything — fan-out included. A rule this
            # expensive to break does not belong in prose alone.
            background=False,
            # Deep reasoning, not maximum reasoning. See hive_worker_effort().
            effort=hive_worker_effort(),
        )
    }


BUILTIN_AGENT_NAMES: tuple[str, ...] = (HIVE_WORKER_AGENT_NAME,)


def list_project_agents(working_dir: str) -> list[tuple[str, str]]:
    """(name, description) of each agent the project defines in ``.claude/agents/``.

    Read for the lead's fan-out brief, so it can dispatch a project specialist
    for a piece that matches one — a generic ``hive-worker`` does not carry the
    project-specific instructions those files do. Deliberately lighter than
    :func:`load_agents_from_directory`: no SDK import, no console output, so it
    is safe to call while building a prompt. Agents without a description are
    skipped (they are skipped at load time too).

    Args:
        working_dir: The project working directory.

    Returns:
        Sorted (by filename) list of ``(name, description)`` pairs; empty when
        the directory is missing or holds nothing usable.
    """
    agents_dir = Path(working_dir) / ".claude" / "agents"
    if not agents_dir.exists():
        return []

    pairs: list[tuple[str, str]] = []
    for agent_file in sorted(agents_dir.glob("*.md")):
        try:
            frontmatter, _ = parse_agent_frontmatter(agent_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        name = frontmatter.get("name") or agent_file.stem
        description = frontmatter.get("description", "")
        if isinstance(name, str) and isinstance(description, str) and description:
            pairs.append((name, " ".join(description.split())))
    return pairs


def project_agent_names(working_dir: str) -> set[str]:
    """Names of every agent the project defines in ``.claude/agents/``.

    Unlike :func:`list_project_agents` this does not require a description: the
    caller needs to know whether a name is *taken*, and an unusable file still
    takes it. Used to decide which built-ins to stand down for.

    Args:
        working_dir: The project working directory.

    Returns:
        The set of names, empty when the directory is missing or unreadable.
    """
    agents_dir = Path(working_dir) / ".claude" / "agents"
    if not agents_dir.exists():
        return set()

    names: set[str] = set()
    for agent_file in agents_dir.glob("*.md"):
        try:
            frontmatter, _ = parse_agent_frontmatter(agent_file.read_text(encoding="utf-8"))
        except Exception:
            names.add(agent_file.stem)
            continue
        name = frontmatter.get("name") or agent_file.stem
        if isinstance(name, str):
            names.add(name)
    return names


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
    """Agent definitions to pass to the SDK for this working directory.

    **Only claudetm's own built-ins** (``hive-worker``). The project's
    ``.claude/agents/*.md`` are deliberately *not* included, because the CLI
    already loads them: ``setting_sources`` includes ``"project"`` (which it
    must, or ``CLAUDE.md`` would not load either), and that is what puts the
    project's agent files in the model's registry.

    Passing them again registered every one of them **twice**. Verified against
    a live session: with a single project agent on disk and the same definition
    passed via ``agents=``, the model reported it "listed twice, identically —
    a duplicate entry in the registry". The two copies are not deduplicated, so
    each project agent's full prompt was in the system prompt of every fan-out
    query twice: ~14k duplicated tokens on a project with 11 agents, ~27k on one
    with 16. And with two identical entries there is no guarantee a dispatch
    resolves to *our* copy anyway, so the duplicate bought nothing.

    The trade-off is deliberate and narrow: the ``background=False`` and default
    turn budget claudetm applies in :func:`load_agents_from_directory` reach only
    the definitions it passes, so a *project specialist* is bound by the fan-out
    brief rather than by its definition. ``hive-worker`` — claudetm's own, and
    the fallback for every piece no specialist fits — keeps both structurally.
    Specialists remain fully usable: the CLI registers them, and
    :func:`list_project_agents` still advertises them in the brief.

    Args:
        working_dir: The project working directory.

    Returns:
        Dictionary of agent_name -> AgentDefinition.
    """
    # Detect and log project configuration
    detect_project_config(working_dir)

    # A project file of the same name still wins — by us standing down, rather
    # than by overwriting. Passing ours alongside would put two definitions of
    # that name in the registry with no rule about which a dispatch resolves to.
    overridden = project_agent_names(working_dir)
    return {
        name: definition
        for name, definition in build_builtin_agents().items()
        if name not in overridden
    }
