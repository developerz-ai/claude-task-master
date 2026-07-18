# 11 — CLI, config, credentials

> Part of [`overview.md`](overview.md). Depends on: none. **Touches credentials handling — no behavior change to token refresh (SDK owns it); changes are validation/masking/locking only.**

## Bad decisions
Phase tool restrictions documented but never shipped (empty default = ALL tools); `start`/`resume` skip the session lock they'd need most; secrets printed unmasked; CLI inputs unvalidated.

## Files to change
- `core/config.py:145-163` — **P1**: `ToolsConfig.planning`/`verification` default `[]` = all tools + `bypassPermissions` → planner can mutate the repo before a plan exists, contradicting CLAUDE.md's phase table. Ship defaults: planning `["Read","Glob","Grep","WebFetch","WebSearch"]`, verification `["Read","Glob","Grep","Bash"]`, working `[]`. Fix `info.py:40` display drift.
- `cli_commands/workflow.py:263,413` — **P1**: `start`/`resume` never call `acquire_session_lock` (only `merge-pr`/`clean` do) → two concurrent runs corrupt state, duplicate PRs, OAuth refresh-token rotation races. Acquire after `exists()`/`validate_for_resume`, release in `finally`, mirror `fix_pr.py:153-161`. (Pairs with the O_EXCL fix in 07.)
- `cli_commands/config.py:125` — **P1**: `config show` dumps `ANTHROPIC_API_KEY`/`OPENROUTER_API_KEY` plaintext (env overrides merged into config). Redact like `_display_env_overrides`; `--show-secrets` opt-in.
- `cli_commands/workflow.py:147-157` + `orchestrator.py:765` — **P2**: `--max-sessions 0` silently = unlimited (falsy check); negatives = instant block; `--prs 0`, `--budget 0`, empty goal all pass. Validate: `max_sessions>=1`, `max_prs>=1`, `budget>0`, `goal.strip()` non-empty (`typer.Option(min=...)`).
- `utils/debug_claude_md.py:86` — hardcoded `claude-haiku-4-5-20251001` — the only model-id policy violation in src. Use `get_config().models.haiku`. Also `:64-69` checks raw `~/.claude/.credentials.json` and omits `env=resolve_runtime_env()` → wrong result under profiles; reuse `CredentialManager` + inject env like `agent_query.py:451`.
- `utils/doctor.py:56` — profile-unaware (hardcodes creds path; api-key profiles report failure while working); docstring claims checks (claude CLI, git) it doesn't run. Use `CredentialManager().verify_credentials()`; add or un-claim the checks.
- `core/profiles.py:373` — removing the ACTIVE profile silently reverts to ambient creds — the exact silent-wrong-account failure `resolve_active` documents preventing. Warn/refuse without `--force` in `profile_remove`.
- `core/credentials.py:369` — api-key profile with missing key returns `""`, fails deep in SDK. Raise `InvalidCredentialsError` when falsy.
- `cli_commands/config.py:166-177` — env-var help table omits `CLAUDETM_MODEL_FABLE`/`CLAUDETM_MODEL_SONNET_1M`; generate from `ENV_VAR_MAPPINGS`.
- `cli.py:403` + `core/state.py:494` — failed `start` leaves orphan state dir (`config.json` without `state.json`) that `clean` refuses to see. `clean` offers removal when dir exists sans state.json.
- `cli.py:414/421` — clean-cancel exits 1 vs 0 inconsistently. Same code for both cancels.
- `cli.py:59-81` — `_fetch_pr_info` uncaught `FileNotFoundError` when `gh` missing → raw traceback. Catch → `PRInfoResult(error=...)`.
- `cli_commands/info.py:98` — `logs --session N` param dead (never referenced). Implement or remove.
- `cli_commands/mailbox.py` — every command defined twice (`mailbox_send` + `_command` wrapper). Register originals directly.

## Tests
- `tests/cli_commands/test_profile.py` (currently ZERO profile CLI tests — multi-account is safety-relevant); validation rejections; config-show masking; concurrent-start lock; planning-phase tool restriction actually reaches `ClaudeAgentOptions.allowed_tools`.

## Done when
- Default install: planner physically cannot Write/Bash; no secret printable without opt-in; invalid CLI input rejected at parse time.
