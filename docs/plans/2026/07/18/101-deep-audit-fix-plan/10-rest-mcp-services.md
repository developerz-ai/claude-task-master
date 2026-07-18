# 10 — REST/MCP dedup: one service layer, delete dead routers

> Part of [`overview.md`](overview.md). Depends on: [`08-api-mcp-security.md`](08-api-mcp-security.md).

## Bad decision
Every capability implemented 2-3 times (REST inline, MCP tools, plus dead router copies) with divergent validation and drifting params. Only `routes_repo.py` delegates properly — extend that pattern everywhere.

## Duplication map (from audit)
| Concern | REST | MCP | Stale copy |
|---|---|---|---|
| status/plan/logs/progress/context | `routes.py:203-616` inline | `tools.get_*` | MCP lacks tail bounds; REST re-implements plan parsing |
| stop/resume/pause/config | `routes.py` inline + DEAD `routes_control.py`/`routes_config.py` | `tools.*` | dead copies diverge; dead cleanup branch deletes whole state dir |
| task init/clean | `routes.py:1004-1183` | `tools.initialize_task/clean_task` | MCP validates neither model nor creds |
| mailbox | `routes.py:1212-1383` | `tools.*` | MCP lacks `metadata` |
| repo clone/setup/plan | `routes_repo.py` → delegates to mcp/tools | shared | shared copy sync/loop-broken (08) |
| webhooks CRUD | `routes_webhooks.py` ad-hoc dicts | none | bypasses `WebhookConfig` models entirely |

## Steps
1. Delete `api/routes_control.py` + `api/routes_config.py` (never imported; divergent semantics; the `routes_control.py:143` cleanup branch deletes every state file including the state.json it just saved). Or promote them to THE implementation and delete the inline copies — pick one, don't keep both.
2. Extract `core/services/`: `TaskService` (status/plan/logs/init/clean/control/config over `StateManager`+`ControlManager`, typed results, one error taxonomy → REST maps to status codes, MCP to result dicts), `RepoService` (path-confined, async via `anyio.to_thread`), `WebhookRegistry` (09).
3. One `validate_model(str) -> ModelType` in `core/agent_models.py` — today REST pattern-allows only `opus|sonnet|haiku` (stale — misses fable/sonnet_1m, `routes.py:1045`), MCP `initialize_task` persists ANY string, `plan_repo` silently coerces unknowns to OPUS. Three behaviors, one input.
4. Fix MCP wrapper drift: `mcp/server.py:224-261` drops `enable_verification`; `send_message` lacks `metadata`; `repo_dir` vs `work_dir` naming. Consider generating the 20 `@mcp.tool` wrappers from a declarative table to kill this bug class.
5. `api/routes.py:767,843` — replace substring-matching on exception text with `except ControlOperationNotAllowedError` / `NoActiveTaskError` (mcp/tools.py already does).
6. MCP `plan_repo` must route through `Planner.create_plan()` — today it calls the agent directly with `context=""`, no coding_style/release_guide/max_prs, and ignores the `model` param (see 13-prompts).

## Tests
- Contract tests hitting both surfaces for the same op, asserting identical validation/results; `tests/api` + `tests/mcp` keep passing.

## Done when
- Zero dead routers; one validation path; MCP and REST accept the same params for the same op.
