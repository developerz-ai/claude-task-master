"""Fan-out brief for a work session — how the lead splits its ONE task.

A work session still owns exactly one plan task. With ``TaskOptions.parallel``
on, the agent running it is a *lead*: it may cut that task into pieces with
**disjoint write sets** and hand each piece to a subagent in the same checkout,
doing everything that overlaps itself. The session reports ``TASK COMPLETE``
exactly as it always has — the orchestrator checks off one task either way and
needs no manifest, no batch and no new bookkeeping.

The calibration is deliberate: subagents exist to do **real, big work**. For a
large task, delegating a few LARGE self-contained pieces is the default posture;
zero workers stays the right answer for anything small or tightly coupled. The
lead is also told about the project's own ``.claude/agents/`` specialists so a
piece matching one is dispatched to it rather than to a generic worker.

This text *is* the feature. Nothing in the orchestrator can tell how big a task
is before it runs, so every judgement below belongs to the lead, and the only
lever we have on it is how well it is briefed. The mechanical bounds are
``max_parallel`` (a ceiling, never a target — see :mod:`.hive`) and the
per-worker turn budget (``AgentDefinition.maxTurns``, see
:func:`~.hive.hive_worker_max_turns`).

Kept out of :mod:`.prompts_working` so that module stays under the 500-LOC house
limit. Pure string building, no I/O.
"""

from __future__ import annotations

from collections.abc import Sequence

#: Section heading used by :func:`~.prompts_working.build_work_prompt`.
FANOUT_SECTION_TITLE = "Parallel Work — You Decide"


def _project_agents_note(project_agents: Sequence[tuple[str, str]] | None) -> str:
    """Render the project-specialists paragraph, or "" when there are none."""
    if not project_agents:
        return ""
    bullets = "\n".join(f"- `{name}` — {description}" for name, description in project_agents)
    return f"""

**This project ships its own specialists — prefer them where they fit.** From `.claude/agents/`:
{bullets}
Match each piece against these FIRST: a specialist carries project-specific instructions a generic
worker lacks, so when a piece fits one of these descriptions, dispatch THAT agent (its
`subagent_type` is its name). Fall back to `hive-worker` only for a piece none of them fits.
Every rule in this section binds a specialist exactly like a worker: exclusive file set,
foreground dispatch, no git, the full four-part brief."""


def build_fanout_section(
    max_parallel: int,
    machine: str = "",
    project_agents: Sequence[tuple[str, str]] | None = None,
) -> str:
    """Build the lead's fan-out brief for the current task.

    Args:
        max_parallel: Safety ceiling on concurrent workers (never a target).
        machine: One-line description of the machine the workers would share
            (see :func:`~.hive.describe_machine`). Empty omits the paragraph.
        project_agents: ``(name, description)`` of the project's own
            ``.claude/agents/`` definitions, so the lead can dispatch a
            specialist for a matching piece. None/empty omits the paragraph.

    Returns:
        The rendered section body.
    """
    machine_note = (
        f"""

**This machine, right now:** {machine}.
Each worker is another agent process reading this repo and running its checks on those same cores,
that same RAM and that same disk. Team size is the smaller of two numbers: how many disjoint pieces
your task has, and how many agent processes this box can actually run — past that, every worker
runs slower and the task finishes later."""
        if machine
        else ""
    )
    return f"""**You may split THIS task across parallel workers — and for a big task, you should.
You are buying speed: this ONE task finished in less wall-clock time.**
A task that spans several modules, layers or features almost always has seams. Map the parts that
can genuinely run at the same time and hand each one to a worker. On a big task your job is to cut
well, brief well, dispatch everything at once, and verify — not to type every edit yourself. A
small or tightly-coupled task you do yourself in sequence — that is a good answer, not a failure.

**Cut BIG pieces, not slivers.** A worker pays a full cold start before its first edit, and it has
its own generous turn budget — so hand it real work that earns both: a whole module, a feature
slice with its own tests and docs, a subsystem sweep. Never scattered micro-edits (observed in a
sibling project: four workers spawned for four one-line edits — four cold starts for work one agent
finishes in a single pass). A few LARGE self-contained pieces beat many small ones.

**Two or more pieces, or none — never exactly one.** A lone worker buys no speed: you pay its cold
start, wait idle, and still verify everything afterwards. So when the cut leaves you holding exactly
one piece to delegate, **fold it back into your own work and dispatch nobody** — that is the correct
resolution, not a smaller split and not a padded one. Zero workers is a legitimate answer any time
the cold start costs more than the work.

Two pieces may run concurrently only if their **write sets are disjoint**: no file either one will
edit is touched by the other, and neither depends on the other's output. And disjoint files are not
enough — **the seam is the API, not the path**: a piece that renames an export, changes a signature
or edits a shared type breaks files no worker owns. Per piece, list what it changes that something
else reads; pull every caller into the same set, or keep that piece yourself. (Observed: one worker
renamed a field across the files it owned, an unowned file kept the old name, and all six workers
reported success.)

**{max_parallel} concurrent workers is a safety ceiling, not a target.** Pick the number of
genuinely disjoint pieces your task actually has — often zero — and never pad a split to look
parallel.{machine_note}{_project_agents_note(project_agents)}

**Dispatch is part of the speed** — the Agent tool: a project specialist where one fits, else
`subagent_type: "hive-worker"`, at most {max_parallel} workers at a time. Put every independent
worker's Agent call **in a single message so they run concurrently** — never in waves when nothing
orders them. While they run, work the pieces you kept: the coupled parts, the shared surface, the
integration. An idle lead waiting on workers it could work alongside is wasted wall-clock.

**Workers run in the foreground — never end your turn while one is live.** Their definitions pin
this, so you do not have to pass anything; what you must not do is finish your turn with a worker
still writing. The session would end underneath it, the orchestrator would find a dirty tree, call
the session unfinished and re-run this whole task from the top.

**Wait for every worker to return before you run the gate or touch git.** No staging, no commit, no
push while any worker is live — you would be committing a half-written tree.

**Turns and cost are shared across the whole hive.** This session has ONE turn budget and ONE cost
cap, and every worker's turns and tokens are charged against them alongside your own. Overrunning
ends the session with nothing committed and re-runs the task. That is the real reason to cut a few
large pieces rather than many small ones: each worker you add spends the same budget you do.

**One checkout, shared by everyone.** Never create a git worktree, never clone, never copy the
project into a per-agent directory — the work has to land in the tree you commit from. The
exclusive file sets are the only lock there is; there is no other coordination mechanism.

**Every brief you write a worker MUST carry four things.** A worker's
tool calls are invisible to you — only its final message comes back — so the brief is everything
it has:
1. its piece of the task, stated in full — never a pointer to something it cannot see,
2. its EXCLUSIVE file set — the only paths it may create or edit,
3. the paths owned by other workers right now, as a flat list of "do not touch",
4. what it cannot read for itself: the API surface its piece must conform to (exact signatures,
   types, names), the decisions you have already made, and the conventions that are not obvious
   from the code. **Point, don't paste.** The worker has this same checkout and reads it as fast
   as you do, so cite `path:line` and let it read; a file excerpt copied into a brief costs you
   the tokens to write it and the worker the tokens to read it, for something it already has.
A worker that needs a file it does not own STOPS and reports the collision instead of resolving it
silently. You then re-cut the boundary or make that change yourself.

**Workers never run git** — no `add`, `commit`, `branch`, `checkout`, `stash`, `push`, ever. You
alone commit, push and open the PR, and you do it only after every worker has returned.

**A worker's report is not evidence** — you never saw what it actually did. Once they return,
verify on disk yourself: `git status`, read the changed files, and run the project's real checks.
Re-do or re-assign anything missing.

**Checks — you decide what a worker may run, and you say so in its brief.** Scoped runs over each
worker's own files are usually fine; they are not when the project's checks share something
exclusive — one database or fixture schema, a fixed port, a single build or coverage directory, a
lock. Look, then put the answer in every brief:
the exact scoped command that worker may run, or explicitly none. "None" is a fine answer —
you run the full gate once at the end regardless.
The repo-wide commands are yours alone in every project — a formatter or autofixer rewrites every
worker's files at once, and an emitting build has them racing over shared output. Never run either
while a worker is live.

**Everything you did not fan out** — dependent work, anything you could not separate — you do
yourself. The task is yours either way; workers are an option, not a hand-off."""


__all__ = ["FANOUT_SECTION_TITLE", "build_fanout_section"]
