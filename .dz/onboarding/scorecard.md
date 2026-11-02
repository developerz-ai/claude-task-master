# AI-first scorecard

> Written by the developerz.ai maintainer agent — established by dz-runner setup mode. Each onboarding run rewrites this file whole; the latest run wins, and the same card is stored on the platform.

- Run: `run_30366c4d30d74816b839d736ce712751`
- Computed: 2026-11-02T04:17:24.981Z
- Proof: **proved** — every command ran green at head.
- Score: 13 of 15 items ok

## `policy` — ok

- .dz/maintainer/maintainer.yml already present, left alone
- .dz/maintainer/reviewer.md established

## `brain` — ok

- CLAUDE.md already present, left alone

## `roster` — ok

- .claude/agents/hive-fanout.md established
- .claude/agents/pr-lifecycle.md established
- .claude/agents/state-persistence.md established
- .claude/agents/github-client.md established

## `skills` — ok

- .claude/skills/verify-change/SKILL.md established
- .claude/skills/local-install/SKILL.md established
- .claude/skills/docs-links/SKILL.md established

## `scripts` — ok

- bin/setup established
- bin/dev established
- bin/check established
- bin/stop established
- down: ./bin/stop (bin)
- ./bin/setup exited 0 at head (0.9s)

## `wiring` — ok

- .mcp.json established

## `commands` — ok

- .claude/commands already present, left alone

## `access` — gap

- landed 0 of 24 asked
- still missing: ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, CLAUDETM_API_KEY, CLAUDETM_PASSWORD, CLAUDETM_WEBHOOK_SECRET, CLAUDETM_WEBHOOK_URL, CLAUDETM_PROFILE, CLAUDETM_TARGET_BRANCH, CLAUDETM_CORS_ORIGINS, CLAUDETM_REST_PORT, CLAUDETM_MCP_PORT, CLAUDETM_SERVER_HOST, CLAUDETM_MCP_TRANSPORT, CLAUDETM_LO…

## `layout` — gap

- migration to the house layout filed as tasks
- apps/claude-task-master: 17 move(s) planned as one task

## `smoke_test` — ok

- tests/core/test_agent_error_classify.py in the repository
- run by ./bin/check exited 0 at head (307.6s)

## `env_example` — ok

- .env.example established

## `agents_md` — ok

- AGENTS.md established

## `per_workspace_brains` — ok

- single-package repository: 0 workspaces
- CLAUDE.md already present, left alone

## `docs_readme` — ok

- docs/README.md established

## `gate_proved` — ok

- ./bin/check exited 0 at head (307.6s)
