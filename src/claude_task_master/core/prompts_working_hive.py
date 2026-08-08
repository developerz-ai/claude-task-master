"""Hive-lead prompt text for Claude Task Master.

The hive mode hands the *remaining tasks of one PR group* to a single "lead"
session instead of running each task in its own session. The lead decides which
of those tasks have disjoint write sets, fans those out to ``hive-worker``
subagents in the same checkout, does the rest itself, and is the only thing in
the run that touches git.

This module holds the hive-only prompt text so ``prompts_working`` stays under
the 500-LOC house limit. Everything here is pure string building — the only
imports are the two literals ``core.hive`` owns (the batch floor and the
manifest label), so the rendered prompt cannot drift from the parser that reads
the lead's answer back.
"""

from __future__ import annotations

from collections.abc import Sequence

from .hive import HIVE_MANIFEST_PREFIX, HIVE_MIN_BATCH_TASKS

#: The manifest label as rendered in the prompt. ``core.hive`` owns the label
#: itself (plural, deliberately distinct from the single-task ``TASK COMPLETE``
#: sentinel); the colon is presentation and belongs here.
MANIFEST_PREFIX = f"{HIVE_MANIFEST_PREFIX}:"


def is_hive_batch(hive_tasks: Sequence[str] | None) -> bool:
    """True when the batch is big enough to be worth a lead session.

    The floor is ``core.hive.HIVE_MIN_BATCH_TASKS`` — the same constant the
    orchestrator uses to decide there is a batch at all. Below it the prompt
    stays byte-identical to the ordinary single-task one.
    """
    return hive_tasks is not None and len(hive_tasks) >= HIVE_MIN_BATCH_TASKS


def numbered_tasks(
    hive_tasks: Sequence[str],
    hive_task_numbers: Sequence[int] | None = None,
) -> list[tuple[int, str]]:
    """Pair each batch task with its 1-based plan number.

    Falls back to a 1..N numbering when no numbers are supplied or the two
    sequences disagree in length — a mislabelled batch is worse than a
    locally-numbered one, and the manifest only has to round-trip.
    """
    if hive_task_numbers is not None and len(hive_task_numbers) == len(hive_tasks):
        return list(zip(hive_task_numbers, hive_tasks, strict=True))
    return [(i, task) for i, task in enumerate(hive_tasks, start=1)]


def build_hive_intro(task_description: str, branch_info: str) -> str:
    """Build the lead framing that replaces the single-task intro."""
    return f"""You are Claude Task Master running as the LEAD of a BATCH of tasks in one PR group.

## Current Task

{task_description}{branch_info}

You own the WHOLE batch listed below — every task in it is yours to deliver, by your own hand or
through workers you dispatch — and you are the ONLY thing here that touches git.
Deliver HIGH QUALITY work; follow project instructions.

Refs: plan `.claude-task-master/plan.md` · progress `.claude-task-master/progress.md`

## Output Style

Terse. No filler, pleasantries, or narration. Don't announce actions — take them.
→ for flow, | for alternatives. Fragments fine.
Code, commits, PRs, JSON: proper syntax.
Status compressed: "added auth middleware → tests pass → 2 files changed".
Completion report: 3-5 lines. What changed, not how."""


def build_task_batch_section(
    hive_tasks: Sequence[str],
    hive_task_numbers: Sequence[int] | None = None,
) -> str:
    """Build the ``## Task Batch`` listing (plan order, 1-based plan numbers)."""
    lines = [
        "Every remaining task of this PR group, in plan order. The numbers are the 1-based plan "
        "numbers — use them verbatim in the completion manifest.",
        "",
    ]
    lines.extend(
        f"{number}. {task}" for number, task in numbered_tasks(hive_tasks, hive_task_numbers)
    )
    return "\n".join(lines)


def build_group_batch_note(create_pr: bool) -> str:
    """Replace the bare 'tasks remaining' count with batch framing."""
    if create_pr:
        note = "This batch is the rest of this PR group — when it is done, you open the PR."
    else:
        note = "This batch does NOT end the PR group — commit only; the orchestrator opens the PR later."
    return f"\n**Your batch is listed under `## Task Batch` below.** {note}"


def build_fanout_section(hive_max_parallel: int = 10) -> str:
    """Build the fan-out rules — the heart of the lead brief."""
    return f"""**You decide what runs in parallel.** Judge the batch above yourself. Two tasks may run at
the same time only if their **write sets are disjoint**: no file either one will edit is touched by
the other, and neither depends on the other's output. If you cannot cut them apart cleanly, do them
yourself in sequence — that is a good answer, not a failure.

**Zero workers is a legitimate answer, and so is one.** Fan-out is not free: every worker pays a
full cold start re-reading the repo. Do not fan out for small or wiring-shaped tasks you could
finish in one focused pass. (Observed in a sibling project: four workers spawned for four one-line
edits — four cold starts for work one agent finishes in a single step.)

**How to fan out** — the Agent tool with `subagent_type: "hive-worker"`, at most {hive_max_parallel}
workers at a time.
Put the independent ones' Agent calls **in a single message so they run concurrently**.

**Pass `run_in_background: false` on EVERY worker.** Agent calls that omit it run in the background,
and a backgrounded worker keeps writing files after you end your turn — the session ends underneath
it, the orchestrator sees a dirty tree, calls the session unfinished and re-runs the whole batch.
Never end your turn while a worker is still running.

**Wait for every worker to return before you run the gate or touch git.** No staging, no commit, no
push while any worker is live — you would be committing a half-written tree.

**Every brief you write a worker MUST name three things:**
1. its task (quote the batch entry, with its plan number),
2. its EXCLUSIVE file set — the only paths it may create or edit,
3. which other workers are live right now, and on which paths.

A worker's tool calls are invisible to you — only its final message comes back — so the brief must
be self-contained: full paths, the task text verbatim, and what its neighbours hold. A worker that
needs a file it does not own STOPS and reports the collision instead of resolving it silently. You
then re-cut the boundary or make that change yourself.

**Workers never run git** — no `add`, `commit`, `branch`, `checkout`, `stash`, `push`, ever. You
alone commit, push and open the PR, and you do it only after every worker has returned.

**A worker's report is not evidence** — you never saw what it actually did. Once they return,
verify on disk yourself: `git status`, read the changed files, and run the project's real checks. A
worker that narrated a change without writing it is a real failure mode — re-do or re-assign that
task yourself.

**Checks:** workers run only narrow checks on their own files. You run the FULL project gate once,
at the end, before committing.

**Everything you did not fan out** — sequential tasks, dependent tasks, anything you could not
separate — you do yourself, in plan order."""


def build_execution_preamble() -> str:
    """Batch framing prepended to the reused per-task execution steps."""
    return (
        "**This is a BATCH, not one task.** The steps below apply to the batch as a whole — where "
        'one says "this task", read it as "this batch". Fan out and/or do the work for every '
        "task you take on, wait for every worker to return, verify their work on disk, then run "
        "the full gate and commit. Never commit while a worker is still running."
    )


def build_completion_opening() -> str:
    """Opening line of the completion section on the hive path."""
    return "**After the WHOLE BATCH is done, STOP.** (Not after the first task — after the batch.)"


def build_manifest_block() -> str:
    """Build the completion manifest contract — which batch tasks actually landed."""
    return f"""**Batch manifest (REQUIRED).** The orchestrator cannot see which tasks you took on, so
you must say so explicitly. On its own final line, list the 1-based plan numbers from
`## Task Batch` whose work you FINISHED and COMMITTED:

```
{MANIFEST_PREFIX} 3, 4, 6
```

- List ONLY tasks whose work is committed. Omit any you did not finish — the orchestrator re-runs
  those. Claiming a task you did not do silently loses that work.
- Finished none? Emit `{MANIFEST_PREFIX}` with nothing after it.
- `{MANIFEST_PREFIX}` (plural, with numbers) is the batch manifest. `TASK COMPLETE` (singular, no
  numbers) is the ordinary end-of-session sentinel. Emit BOTH, on separate lines, manifest last."""


def build_end_instruction() -> str:
    """Replacement for the single-task ``End with: TASK COMPLETE`` line."""
    return f"""End with these two lines, in this order:

```
TASK COMPLETE
{MANIFEST_PREFIX} <plan numbers you finished AND committed, comma-separated>
```"""
