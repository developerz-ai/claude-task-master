# developerz-ai/claude-task-master — docs

> Index — established by dz-runner setup mode. Add a line when you add a page.

| Where | What lives there |
|---|---|
| [`idea/`](idea/) | Why this repository is shaped the way it is: the product idea, the architecture, the principles a change is weighed against. *(not created yet)* |
| [`standards/`](standards/) | How work is done here: the rules a change follows, and for each rule the check that enforces it. *(not created yet)* |
| [`mcp-optional-integrations.md`](mcp-optional-integrations.md) | The MCP servers that need a token (Sentry, developerz.ai): how to enable them in your own user-local configuration. |

The brain itself is the repo root's [`CLAUDE.md`](../CLAUDE.md); the
commands are `bin/{setup,dev,check,stop}`. The project's shared MCP wiring is
[`.mcp.json`](../.mcp.json); it asks for no credentials, so an ordinary
checkout loads it as is.
