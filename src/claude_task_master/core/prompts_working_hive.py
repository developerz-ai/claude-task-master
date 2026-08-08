"""Fan-out brief for a work session — how the lead splits its ONE task.

A work session still owns exactly one plan task. With ``TaskOptions.parallel``
on, the agent running it is a *lead*: it may cut that task into pieces with
**disjoint write sets** and hand each piece to a ``hive-worker`` subagent in the
same checkout, doing everything that overlaps itself. The session reports
``TASK COMPLETE`` exactly as it always has — the orchestrator checks off one
task either way and needs no manifest, no batch and no new bookkeeping.

This text *is* the feature. Nothing in the orchestrator can tell how big a task
is before it runs, so every judgement below — whether to fan out at all, how
many workers, where the seams are — belongs to the lead, and the only lever we
have on it is how well it is briefed. The one mechanical bound is
``max_parallel`` (see :mod:`.hive`), and it is a ceiling, not a target.

Kept out of :mod:`.prompts_working` so that module stays under the 500-LOC house
limit. Pure string building, no I/O.
"""

from __future__ import annotations

#: Section heading used by :func:`~.prompts_working.build_work_prompt`.
FANOUT_SECTION_TITLE = "Parallel Work — You Decide"


def build_fanout_section(max_parallel: int) -> str:
    """Build the lead's fan-out brief for the current task.

    Args:
        max_parallel: Safety ceiling on concurrent workers (never a target).

    Returns:
        The rendered section body.
    """
    return f"""**You may split THIS task across parallel workers — you decide whether that is worth it.**
Judge your own task. Two pieces of it may run at the same time only if their
**write sets are disjoint**: no file either one will edit is touched by the other, and
neither depends on the other's output. If you cannot cut them apart cleanly, do the task
yourself in sequence — that is a good answer, not a failure.

**Zero workers is a legitimate answer, and so is one.** Most tasks are one task for a reason. Fan-out
is not free: every worker pays a full cold start re-reading the repo, and its report is the only
thing you get back. Do not fan out a small or wiring-shaped task you could finish in one focused
pass. (Observed in a sibling project: four workers spawned for four one-line edits — four cold
starts for work one agent finishes in a single step.)

**{max_parallel} concurrent workers is a safety ceiling, not a target.** Never pick a number because
it is allowed; pick the number of genuinely disjoint pieces your task actually has, which is usually
zero.

**How to fan out** — the Agent tool with `subagent_type: "hive-worker"`, at most {max_parallel}
workers at a time.
Put the independent ones' Agent calls **in a single message so they run concurrently**.

**Pass `run_in_background: false` on EVERY worker.** Agent calls that omit it run in the background,
and a backgrounded worker keeps writing files after you end your turn — the session ends underneath
it, the orchestrator sees a dirty tree, calls the session unfinished and re-runs the whole task.
Never end your turn while a worker is still running.

**Wait for every worker to return before you run the gate or touch git.** No staging, no commit, no
push while any worker is live — you would be committing a half-written tree.

**One checkout, shared by everyone.** You and every worker work directly in this same checkout.
Never create a git worktree, never clone, never copy the project into a per-agent directory —
the work has to land in the tree you commit from. The exclusive file sets below are the
only lock there is; there is no other coordination mechanism.

**Every brief you write a worker MUST name three things:**
1. its piece of the task — what to do, in full, not a pointer to something it cannot see,
2. its EXCLUSIVE file set — the only paths it may create or edit,
3. which other workers are live right now, and on which paths.

A worker's tool calls are invisible to you — only its final message comes back — so the brief must
be self-contained: full paths, the work stated verbatim, and what its neighbours hold. A worker that
needs a file it does not own STOPS and reports the collision instead of resolving it silently. You
then re-cut the boundary or make that change yourself.

**Workers never run git** — no `add`, `commit`, `branch`, `checkout`, `stash`, `push`, ever. You
alone commit, push and open the PR, and you do it only after every worker has returned.

**A worker's report is not evidence** — you never saw what it actually did. Once they return,
verify on disk yourself: `git status`, read the changed files, and run the project's real
checks. A worker that narrated a change without writing it is a real failure mode — re-do or
re-assign that piece yourself.

**Checks:** workers run only narrow checks on their own files. You run the FULL project gate once,
at the end, before committing.

**Everything you did not fan out** — dependent work, anything you could not separate — you do
yourself. The task is yours either way; workers are an option, not a hand-off."""


__all__ = ["FANOUT_SECTION_TITLE", "build_fanout_section"]
