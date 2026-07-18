# 06 — Cross-process control: make stop/pause/config actually work

> Part of [`overview.md`](overview.md). Depends on: none.

## Bad decision
The orchestrator holds one long-lived in-memory `TaskState` and never re-reads disk, while REST/MCP/CLI control paths write state from *other processes*. Every external signal is either invisible (in-process `threading.Event`) or clobbered by the orchestrator's next `save_state`.

## Files to change
- `core/control.py:304-310` + `core/shutdown.py:47,117` — **P1**: `stop()` calls `request_shutdown()` — a process-local Event; no-op when orchestrator is a different process (CLI run vs server). `POST /control/stop` returns 200 while the run continues.
- `core/orchestrator.py` (all `save_state` sites) + `core/state.py` `RESUMABLE_STATUSES` — **P1**: on-disk `stopped`/`paused` clobbered because `"stopped"→"working"` is a valid transition and the orchestrator saves its stale in-memory status.
- `core/control.py:332` + `api/routes.py:928` — **P2**: `PATCH /config` load-modify-save reverted by orchestrator's next save of stale `state.options`.
- `core/control.py:315-321` — **P2**: `stop(cleanup=True)` runs `cleanup_on_success` while the orchestrator may still be live → next `save_state` recreates a half-populated state dir (`state.json` without goal/plan) → later `load_goal()` FileNotFoundError.

## Steps
1. Introduce a durable control channel: either a `control_requested: "stop"|"pause"|None` field written by ControlManager with its own tiny file (`control.json`), or reuse status but make it authoritative (below). Orchestrator polls it each loop cycle next to the existing `is_cancellation_requested()` check (orchestrator.py:827).
2. Reload-merge-save discipline: before every `save_state`, re-read on-disk status/options; treat externally-set `stopped`/`paused` (and option changes) as authoritative — never overwrite except via explicit `operation="resume"`.
3. `stop(cleanup=True)`: wait for `is_session_active()` to go false (bounded) before cleanup; log dropped mailbox messages.
4. Delete the dead divergent copies `api/routes_control.py` + `api/routes_config.py` (see 10) — the dead `cleanup` branch there deletes the entire state dir including the just-saved state.json.

## Tests
- `tests/core/test_control.py`: cross-process stop honored within one cycle; config patch survives orchestrator save; stop+cleanup doesn't race a live orchestrator (simulate with a second StateManager instance).

## Done when
- `claudetm-server` stop/pause/config-patch verifiably affect a CLI-launched run; no state clobber under interleaved saves.
