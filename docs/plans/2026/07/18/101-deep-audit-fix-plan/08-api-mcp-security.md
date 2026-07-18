# 08 — API/MCP security + async correctness

> Part of [`overview.md`](overview.md). Depends on: none. **Security-sensitive slice — contains an unauthenticated-RCE chain. Land first among API slices. Nothing here touches the publish path, but auth changes must be tested against both REST and MCP transports before release.**

## Bad decisions
Auth is opt-in with REST merely *warning* on public binds; repo endpoints accept arbitrary filesystem paths and execute repo-supplied shell scripts; sync subprocess work runs inline on the event loop.

## Files to change
- `mcp/tools.py:1591-1613,1205` + `api/routes_repo.py:107,180` + `api/server.py:402-407` — **P0 RCE chain**: `claudetm-api --host 0.0.0.0` with no `CLAUDETM_PASSWORD` → `POST /repo/clone` (arbitrary `target_dir`, no workspace confinement) + `POST /repo/setup` (runs repo's `setup.sh` with server privileges) = unauthenticated RCE; clone alone = arbitrary-filesystem-write. MCP server hard-exits without auth on network transport (`mcp/server.py:734-740`) but REST only warns — inconsistent. Fix: refuse repo endpoints when `not is_auth_enabled()`; confine `target_dir`/`work_dir` under `DEFAULT_WORKSPACE_BASE` (reject `resolve()` escaping it); explicit opt-in flag for setup-script execution; mirror the MCP `SystemExit` in `api/server.py:run_server`.
- `core/agent_phases.py:33-79` + `mcp/tools.py:1784` + `api/routes_repo.py:266` — **P0**: `run_async_with_cleanup` calls `loop.run_until_complete` from threads with a running loop — `POST /repo/plan` and MCP `plan_repo` ALWAYS raise `RuntimeError: Cannot run the event loop...`, surfaced as 400 "Planning failed". Fix: `await anyio.to_thread.run_sync(...)` in the handler + `async def` MCP tool; or guard `run_async_with_cleanup` to spawn a fresh thread when `get_running_loop()` succeeds. Also `finally: asyncio.set_event_loop(None)` — it currently leaves a closed loop as thread-current.
- `api/routes_repo.py:107,180` + `mcp/server.py:493,528` — **P0**: `clone_repo`/`setup_repo` fully sync (minutes of subprocess) inside async handlers → whole server frozen. Thread-offload (or declare handlers plain `def` for Starlette threadpooling).
- `api/routes_webhooks.py:854-949,132-138` — **P1 SSRF**: `POST /webhooks/test` POSTs to any URL (`169.254.169.254`, localhost ports) with attacker-controlled stored headers; returns status+timing = internal port scan. Fix: resolve-and-reject private/link-local/loopback post-DNS; require auth for `/webhooks*`; deny-list hop headers.
- `api/server.py:72-73,110` — **P1**: `CLAUDETM_API_KEY` documented as auth but NEVER checked; startup log prints its truncated value — and profile.py:77 uses the same env var for the real Anthropic key → credential fragment in logs. Implement the check or delete; rename one of the vars.
- `mcp/tools.py:465-518` — `clean_task(state_dir=X, force=True)` rmtree's ANY dir containing a `state.json`; combined with clone = arbitrary tree deletion. Constrain `state_dir` inside `work_dir`.
- `auth/password.py:233` + `auth/middleware.py:353` — non-ASCII password → `secrets.compare_digest` TypeError → 500 instead of 403. Compare UTF-8 bytes.
- `api/routes_webhooks.py:459` — `GET /webhooks` returns auth headers verbatim (doc promises masking) → leaks bearer tokens. Mask like `secret`→`has_secret`.
- `webhooks/client.py:404-412` — legacy `X-Webhook-Signature` (no timestamp) replayable forever. Deprecate/remove or document replay-unsafe.
- `server.py:50-52` + `mcp/server.py:621` — `CLAUDETM_MCP_TRANSPORT` unvalidated Literal cast; typo silently changes transport. Validate against `{"sse","streamable-http"}` at startup. Note `BaseHTTPMiddleware`+SSE streaming hazard — add targeted test or move to pure-ASGI middleware.
- `api/routes.py:433` + `mcp/tools.py:320` — `/logs` reads whole file with `readlines()` on the loop; MCP `tail=0` returns ENTIRE file (`lines[-0:]`), negatives nonsense. Validate `tail >= 1`; read via `deque(f, maxlen=tail)`; thread-offload.

## Tests
- `tests/api/` + `tests/mcp/`: unauth'd repo endpoints refused; path escape rejected (`target_dir=/tmp/x`, `../`); plan_repo works from a running loop; SSRF targets rejected; non-ASCII password → 403; webhook list masks headers.

## Done when
- No mutating/subprocess endpoint reachable without auth; no sync subprocess on the event loop; `POST /repo/plan` returns a plan.
