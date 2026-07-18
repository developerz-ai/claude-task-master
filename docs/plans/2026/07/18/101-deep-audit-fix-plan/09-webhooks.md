# 09 — Webhooks: wire the registry, fix delivery

> Part of [`overview.md`](overview.md). Depends on: [`08-api-mcp-security.md`](08-api-mcp-security.md) (SSRF/masking fixes touch same files).

## Bad decisions
Two webhook systems that never meet: REST CRUD writes `webhooks.json` nobody reads; the orchestrator emits only to a single CLI `--webhook-url`. Retry loop off-by-one makes `max_retries=0` deliver nothing.

## Files to change
- `core/orchestrator.py:104-180` + `api/routes_webhooks.py` — **P1**: registered webhooks NEVER receive events — `WebhookEmitter` wraps one `WebhookClient` from `--webhook-url`; nothing reads `webhooks.json`. Fix: `WebhookRegistry` service (locked, atomic storage built on `webhooks/config.py` `WebhookConfig` — currently also unused) consumed by both the CRUD routes AND a fan-out emitter in `_run_work_loop`, filtering with `should_send_event`.
- `webhooks/client.py:447,598` — **P1**: `while attempt < max_retries` treats retries as total attempts: `max_retries=0` (allowed, ge=0) = zero deliveries, silent; default 3 = 2 retries. Also pointless up-to-30s backoff sleep after the FINAL failure (`:496,522,630`). Fix: `attempt <= max_retries`; sleep only when another attempt remains. Unify `send`/`send_sync` (line-for-line duplicates) so the fix lands once.
- `api/routes_webhooks.py:407-420,562-604` — **P1**: registry read-modify-write unlocked (concurrent POST loses one) and `_save_webhooks` truncate-writes in place — crash = truncated JSON → `_load_webhooks` returns `{}` → all registrations silently discarded on next save. Fix in the `WebhookRegistry` extraction: flock + tmp+rename (share `_atomic_write_json`, see 07).
- `core/orchestrator.py:162` — **P2**: `emit` docstring says fire-and-forget but calls `send_sync` — dead endpoint stalls the work loop ~100s per event. Deliver via background single-worker thread queue (preserves ordering) or cap timeout/retries on emit paths.
- `webhooks/events.py:169` — base `event_type` defaults to `TASK_STARTED` → forgotten override silently misclassifies. Make it required / raise in `__post_init__`.
- `api/routes_webhooks.py:214-221,690-765` — `WebhookUpdateRequest.has_updates()` never called (`PUT {}` "succeeds"); secret clearable only via empty string, undocumented. 400 on no-op update; document/replace sentinel.
- `webhooks/config.py` — `WebhooksConfig` container unused: wire into `WebhookRegistry` or delete.

## Tests
- `tests/webhooks/` + `tests/api/`: registered webhook receives run.started; `max_retries=0` = exactly 1 attempt; concurrent creates both survive; kill mid-save doesn't lose registry; emit doesn't block the loop (timing assert with dead endpoint).

## Done when
- `POST /webhooks` → run task → events delivered, filtered per config; retry semantics match the documented "0-10 retry attempts".
