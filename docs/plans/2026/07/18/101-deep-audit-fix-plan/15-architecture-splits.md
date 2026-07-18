# 15 — Architecture: split every file over 500 LOC

> Part of [`overview.md`](overview.md). Depends on: 14 (deletions shrink the list first; conversation.py 525 disappears entirely). Do LAST — mechanical moves after behavior fixes, so fix-PRs don't conflict.

## Bad decision
Repo's own rule is 500 LOC max / SRP; 19 files violate it, and the violations caused real bugs (4 plan parsers, 2 complexity maps, orchestrator's second PR lifecycle with different retry caps, REST/MCP triplication).

## Splits (audit-verified symbol moves)
- `mcp/tools.py` 1835 → `mcp/models.py` (16 Result BaseModels), `tools_info.py`, `tools_task.py`, `tools_mailbox.py`, `tools_repo.py` (+ decompose 350-line `setup_repo` into `_detect_package_manager`/`_install_dependencies`/`_run_setup_scripts`), `resources.py`. (10's service extraction shrinks these further.)
- `core/orchestrator.py` 1609 → `webhooks/emitter.py` (WebhookEmitter + `_emit_*`, ~350), `core/mailbox_processor.py` (~190), `core/verification_fix.py` (`_verify_success`…`_fix_pr_ci_failure` — and make it REUSE `WorkflowStageHandler` CI polling instead of the divergent copy), `orchestrator_errors.py`; run loop stays <550.
- `api/routes.py` 1433 → `routes_info.py`, `routes_task.py`, `routes_mailbox.py`, real `routes_control.py`, `route_helpers.py`; keep `register_routes`.
- `core/workflow_stages.py` 1266 → `core/stages/{git_ops,ci,reviews,merge,release}.py` + thin dispatcher facade sharing a context dataclass; move ~400 LOC of embedded prompt templates to `core/prompts_pr_fix.py` (matches prompts_* convention). `_get_current_branch` currently defined 3× (orchestrator:371, workflow_stages:60, task_runner:40) → `git_ops` only.
- `webhooks/events.py` 993 → preferred: generic `dataclasses.fields()`-driven `to_dict` on the base (deletes ~500 LOC, no split needed); else split events_run/events_pr/event_base/factory.
- `api/routes_webhooks.py` 980 → `webhook_api_models.py`, `webhook_store.py` (→ `WebhookRegistry`, see 09), handlers.
- `api/models.py` 919 → `models_task.py`, `models_repo.py`, `models_mailbox.py`, `models_common.py`.
- `mcp/server.py` 821 → `tool_registration.py` (or declarative table — kills wrapper-drift bug class, see 10), `runner.py`.
- `webhooks/client.py` 703 → `signatures.py`, `delivery.py`, client; unify duplicate `send`/`send_sync` retry loops (09's fix lands once).
- `core/state.py` 700 → `state_models.py` (TaskState/TaskOptions — also breaks the state_backup circular import), `state_locking.py` (flock + PID lock; 07's fixes land here), `state_io.py` (`_atomic_write_json` shared with mailbox/webhooks), facade <300. Longer-term: replace 4-way mixin inheritance (abstract stubs raising NotImplementedError shadowed by MRO) with composition.
- `core/pr_context.py` 695, `core/agent_query.py` 668 (→ `agent_retry.py` + `agent_stream.py`; inject `get_model_name_func`/`process_message_func` once in `__init__` instead of threading through every call), `cli_commands/workflow.py` 576 (extract shared `_prepare_run` — start/resume duplicated tail already drifted: webhook validation only in start), `core/task_runner.py` 566, `webhooks/config.py` 565, `api/server.py` 551 (→ `api/config.py`), `core/config_loader.py` 541 (→ `config_paths.py`, `config_env.py`), `github/client_pr.py` 539.
- `auth/middleware.py` 448 (under limit) — dedupe the twice-implemented verification flow into one `_verify_request` helper.
- Consolidate 4 model-name maps (`agent.py`, `agent_query.py`, `config.py`; conversation.py's deleted in 14) into `config.get_model_name`.

## Steps
1. One PR per bullet-group, move-only (no behavior edits — those landed in 01-13). `git mv`-style diffs, update imports, keep public API via `__init__` re-exports where external callers exist.
2. After each: `pytest && ruff check . && mypy .`

## Done when
- `find src -name "*.py" | xargs wc -l | awk '$1>500'` → empty (excluding total line).
