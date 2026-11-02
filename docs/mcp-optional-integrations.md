# Optional MCP integrations

The repository's [`.mcp.json`](../.mcp.json) wires the MCP servers every
checkout can run. It asks for no credentials, so an ordinary OAuth-only clone
loads the project wiring without a missing-variable complaint.

Two further integrations need an API token. They live in **your own** Claude
Code configuration — user scope, never committed — so they are opt-in:

| Integration | Credential | Purpose |
|---|---|---|
| `sentry-mcp` | `SENTRY_ACCESS_TOKEN` | Query Sentry issues from a session |
| `developerz` | `DEVELOPERZ_API_KEY` | The developerz.ai MCP endpoint |

## Why they are not in `.mcp.json`

`.mcp.json` is committed, so every clone of the repository reads it. Claude Code
expands `${VAR}` in a server's `env` and `headers` when it loads the file, from
the environment of the session that loads it. A reference to a variable that is
not set leaves that server unusable, and for an HTTP server the CLI says so
outright:

```
MCP config diagnostics ⚠

[Contains warnings] Project config (shared via .mcp.json)
Location: /path/to/claude-task-master/.mcp.json
 └ [Warning] [developerz] mcpServers.developerz: Missing environment variables: DEVELOPERZ_API_KEY
```

A checkout that never touches Sentry or developerz.ai still pays for that
wiring — and the project file cannot ask for credentials that only some
machines have.

## Enable one

User scope (`~/.claude.json` → `mcpServers`) applies to every project on the
machine and is never committed. Add the server once:

```bash
# Sentry — needs SENTRY_ACCESS_TOKEN in the environment
claude mcp add --scope user sentry-mcp \
  -e 'SENTRY_ACCESS_TOKEN=${SENTRY_ACCESS_TOKEN}' \
  -- bunx @sentry/mcp-server

# developerz.ai — needs DEVELOPERZ_API_KEY in the environment
claude mcp add --scope user --transport http developerz \
  https://mcp.developerz.ai/v1/mcp \
  -H 'Authorization: Bearer ${DEVELOPERZ_API_KEY}'
```

The `${VAR}` references are expanded when Claude Code loads the configuration,
so the token itself stays in your environment and never lands in a file. The
Sentry server runs through `bunx`, so `bun` has to be installed.

### Provide the credential

Either export it in the shell that starts Claude Code:

```bash
export SENTRY_ACCESS_TOKEN=...      # or: export DEVELOPERZ_API_KEY=...
```

or keep it in your user-local settings (`~/.claude/settings.json`):

```json
{
  "env": {
    "SENTRY_ACCESS_TOKEN": "..."
  }
}
```

### By hand

The same two servers, to merge into `~/.claude.json` under `mcpServers`:

```json
{
  "mcpServers": {
    "sentry-mcp": {
      "type": "stdio",
      "command": "bunx",
      "args": ["@sentry/mcp-server"],
      "env": {
        "SENTRY_ACCESS_TOKEN": "${SENTRY_ACCESS_TOKEN}"
      }
    },
    "developerz": {
      "type": "http",
      "url": "https://mcp.developerz.ai/v1/mcp",
      "headers": {
        "Authorization": "Bearer ${DEVELOPERZ_API_KEY}"
      }
    }
  }
}
```

`SENTRY_HOST` is only needed for a self-hosted Sentry — the server talks to
sentry.io otherwise — so it is left out here. Add it as
`"SENTRY_HOST": "${SENTRY_HOST}"` when you need it.

### Verify

```bash
claude mcp list
```

The server shows up under the user config. If the credential is not visible to
Claude Code, the diagnostic above appears against the user config instead of
the project config: export the variable and start a new session.

### Remove one

```bash
claude mcp remove --scope user sentry-mcp
```
