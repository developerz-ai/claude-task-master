# 12 — Agent SDK integration: result handling, cancellation, RAII

> Part of [`overview.md`](overview.md). Depends on: none.

## Bad decisions
Session success is hardcoded `True` regardless of `ResultMessage.is_error`; Ctrl+C can't interrupt a running query; safety hooks are silently disabled; retries replay full sessions after side effects.

## Files to change
- `core/agent_phases.py:228` + `core/agent_message.py:98-119` — **P1**: nothing inspects `ResultMessage.is_error`/`subtype` (`error_max_turns`, `error_during_execution`, `error_max_budget_usd`); `run_work_session` hardcodes `"success": True` → budget-killed half-done work marked `[x]`. Capture in `MessageProcessor.process_message`, derive `success` from it.
- `core/agent_query.py:542-549` — **P1**: end-of-turn detection ignores `parent_tool_use_id` — a Task-subagent's `end_turn` arms the 120s post-completion idle timeout while the parent still works → session truncated mid-task, marked success. Skip messages with `parent_tool_use_id is not None`.
- `core/orchestrator.py:798` + `core/shutdown.py:76-83,205-216` — **P1**: SIGINT handler only sets a flag; zero `add_shutdown_callback` callers; cancellation polled only between cycles → Ctrl+C during a 30-min session does nothing; exit-code-2 path unreachable mid-session. Register a callback that cancels the in-flight query task (`loop.call_soon_threadsafe(main_task.cancel)`) or check `is_shutdown_requested()` in the `_execute_query` watchdog loop. Also shutdown.py:205: handler calls `run_callbacks()` acquiring a non-reentrant lock → signal during `add_callback` deadlocks; handler must ONLY set the Event, callbacks run from the polling side.
- `core/agent.py:94-98` — **P1**: `self.hooks = {}` unconditionally discards caller hooks + `enable_safety_hooks`; `_init_default_hooks` unreachable → all of `hooks.py` (479 LOC dangerous-command blocker) dead while callers believe it's on. Decide: honor explicit hooks, or delete the subsystem honestly (per the documented Stream-closed workaround). If kept: fix bypass gaps (hooks.py:102-173 — `rm -fr /`, `rm -rf ~` no slash, `$HOME`, `git push -f`).
- `core/agent_query.py:340-354,302-328` — **P2**: blanket `except Exception` retries non-retryable errors by replaying the ENTIRE session; mid-stream transient retry after the agent already pushed/opened a PR → duplicates. Track whether any ToolUseBlock streamed; if so return accumulated text / don't replay; route unknowns through `_classify_api_error`, re-raise non-transient.
- `core/agent_query.py:426-433` — **P2**: `ModelType.FABLE` maps to no complexity → `effort_level=None` — the 2x-priced tier runs WITHOUT extended thinking while Opus gets `max`. Replace reverse-lookup with direct `MODEL_EFFORT_MAP` in `agent_models.py` (fable→`max`).
- `core/agent_models.py:121-127` — fallback single-hop (`fallback_model` once): Fable→Opus only; docs promise chain to Haiku. Implement chain retry on model-unavailable in `_run_query_with_retry`, or fix docs. Guard HAIKU↔SONNET cycle.
- `core/agent_models.py:179-185` — `parse_task_complexity` matches tags ANYWHERE (quoted `[quick]` in text wins over trailing `[coding]`) and strips all occurrences. Take last/anchored match, `count=1` sub.
- `core/agent_models.py:164` vs `core/task_group.py:28-90` — `TaskComplexity` duplicated (enum→ModelType vs enum→str); silent divergence. Delete task_group copy (pairs with 01).
- `core/agent_query.py:388-409` — process-global `os.chdir` races concurrent queries in server mode; `cwd=` is already passed to the SDK (`:464`). Drop the chdir.
- `core/agent_query.py:305` — stream-stall detection via float equality `e.timeout == STREAM_IDLE_TIMEOUT_SEC` miscounts when env-overridden to 30 (collides with `_classify_api_error`'s 30.0). Raise a dedicated `StreamStallError` subclass, isinstance-check.
- `core/agent_query.py:229-235` — `retry_after` honored unbounded; each long sleep exceeds the 60s failure window → consecutive-failure threshold never trips for slow 429s. Cap retry_after; count attempts per `run_query` invocation.
- `core/rate_limit.py:107-119` — no jitter → multi-instance lockstep retries. Add decorrelated jitter.
- `core/circuit_breaker.py:204-232,295-310` — HALF_OPEN wedges permanently when `success_threshold > half_open_max_calls` (counter never decrements, no timeout); `__exit__` counts `CancelledError`/`KeyboardInterrupt` as API failures → user interrupts open the breaker. Fix both; validate config invariant. (Most of the module is dead surface — see 14.)
- `core/key_listener.py:39-117` — stop/start race restores terminal to cooked mode under an active listener (unsynchronized `_original_settings`, late `finally` after new `setcbreak`); after Escape, `_running` stays True so restart no-ops. Lock settings, join before restore, reset `_running` in listener `finally`.
- `core/shutdown.py:98-103` — `unregister` skips `None` originals, leaving stale handler installed. Restore `SIG_DFL` when original is None. Also `interruptible_sleep` busy-polls — use `Event.wait(...)`.
- `core/agent_query.py:617-620` — `_default_process_message` unguarded `result_text = message.result` overwrites with None on error results. Add `and message.result` guard.
- Cost accounting — `ProgressTracker.record_api_call` zero callers; nothing reads `ResultMessage.total_cost_usd`/`usage` → every run reports $0.00. Feed tracker from `MessageProcessor` on ResultMessage; drop hand-rolled token pricing.

## Tests
- `tests/core/test_agent_message.py` (currently NONE for MessageProcessor): is_error propagation, subagent end_turn ignored, None-result guard. `test_agent_models_fallback.py`: chain, effort map, tag parsing. Signal test: SIGINT mid-query → exit 2 promptly.

## Done when
- Errored/budget-capped sessions report failure; Ctrl+C interrupts within seconds; fable gets `max` effort; no full-session replay after streamed tool use.
