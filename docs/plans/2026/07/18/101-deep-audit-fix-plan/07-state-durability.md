# 07 — State durability: locks, fsync, backups, logs

> Part of [`overview.md`](overview.md). Depends on: none.

## Bad decisions
Atomicity assumed from tmp+rename alone (no fsync); backups only ever written on pause but restored blindly; PID lock is check-then-act; JSON logs rewritten in place and discarded on corruption.

## Files to change
- `core/state.py:457-479` (`_atomic_write_json`) — no fsync of file or dir before/after rename → crash can leave empty state.json. Add `f.flush(); os.fsync(fd)` + dir fsync after rename. Same in `mailbox/storage.py:84` (or share this helper — see 05).
- `core/state_backup.py:57-90` + `orchestrator.py:813` — **P1**: backups created ONLY on pause; `_attempt_recovery` silently restores the newest backup however stale → resume redoes merged tasks, duplicate PRs, `--prs` counters rolled back. Fix: `create_state_backup()` on every successful `save_state` (rotate N); on restore compare backup `updated_at` vs corrupt file mtime, warn loudly, refuse if older by threshold.
- `core/state.py:346-353,378` — validation read happens BEFORE acquiring the exclusive lock (TOCTOU); `load_state` holds a *shared* lock while `_attempt_recovery` WRITES state.json under it. Move validation load inside `file_lock`; recovery must take exclusive lock or return recovered state without rewriting.
- `core/state.py:230-279` — PID session lock: `is_session_active()` check then plain `write_text` — two `claudetm start` both acquire; recycled PID false-positives block forever. Use `O_CREAT|O_EXCL` (or an flock-held fd for process lifetime); store pid+start-time.
- `core/state.py:151-194` + `state_backup.py:141` — cleanup deletes `.state.lock` while possibly held → flock rebinds to a new inode, two holders. Exclude lock/pid files from cleanup. Wrap `st_mtime`-key sorts against vanishing files.
- `core/state.py:115-144` — no `schema_version` in state.json; cross-version resume undefined (pydantic silently drops newer fields, then destroys them on save). Add `schema_version: int` + `_migrate_state(data)` table in `load_state`.
- `core/logger.py:261-282` — JSON entries buffered until `end_session` (crash loses the errors you need); `_flush_json` rewrites the whole file in place and on parse error `except: pass # Start fresh` discards ALL history; O(n²). Switch to JSONL append.
- `core/state_pr.py:44,144,211,236` — `get_pr_dir` mkdirs on read paths (dead `exists()` guard, litters dirs); `mark_threads_addressed` writes in place → corrupt file = re-answered threads/duplicate comments. Split path-accessor vs `ensure_pr_dir`; use `_atomic_write_json`.
- `core/state_pr.py:106-131` — `save_ci_failure` dead code writing `.txt` that `load_pr_context` (rglob `*.log`) would never read. Delete; fix doc-comment at state.py:598 and CLAUDE.md path claims (`pr-{number}/ci/*.txt` vs actual `debugging/pr/{number}/ci/*.log`).
- `core/context_accumulator.py:13-44` — context.md grows unbounded and is injected whole into every prompt (matters once 13-prompts wires it up). Cap `get_context_for_prompt` (last N sessions / M chars) + LLM re-summarize past threshold.
- `core/state_recovery.py:58-68` + `github/client.py:149` — `detect_real_state(cwd=…)` resolves PR number in `cwd` but `get_pr_status` queries the process CWD's repo → server mode recovers state from the WRONG repository. Thread `cwd` through `get_pr_status`/`_get_repo_info`.
- `core/checkpoint.py` — CheckpointManager is memory-only (`to_dict`/`from_dict` never persisted), `keep_count` never enforced. Persist or delete (see 14).
- `core/progress_tracker.py:53-58` — cost table labeled Opus uses Sonnet prices (also 12).

## Tests
- `tests/core/`: crash-sim (truncate state.json mid-write → recovery refuses stale backup), two concurrent `start` (one must lose), JSONL logger survives kill -9, schema migration round-trip.

## Done when
- kill -9 at any point loses at most the last write; no silent stale-state restore; single-instance guarantee holds.
