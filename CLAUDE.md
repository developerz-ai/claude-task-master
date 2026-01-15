# CLAUDE.md

Project instructions for Claude Code when working with Claude Task Master.

## Project Overview

Autonomous task orchestration system that uses Claude Agent SDK to keep Claude working until a goal is achieved. Uses OAuth credentials from `~/.claude/.credentials.json` for authentication.

**Core Philosophy**: Claude is smart enough to do work AND verify it. Task master keeps the loop going and persists state.

## Quick Start

```bash
# Setup
uv sync                          # Install dependencies
uv run python -m claude_task_master.cli doctor  # Check system

# Usage
cd <project-dir>
uv run python -m claude_task_master.cli start "Your task here" --max-sessions 10
uv run python -m claude_task_master.cli status   # Check progress
uv run python -m claude_task_master.cli plan     # View task list
uv run python -m claude_task_master.cli clean -f # Clean state
```

## Development

```bash
pytest                    # Run tests
ruff check . && ruff format .  # Lint & format
mypy .                    # Type check
```

## Architecture

**Components** (Single Responsibility):
1. **Credential Manager** - OAuth from `~/.claude/.credentials.json` (nested `claudeAiOauth` structure)
2. **State Manager** - Persistence to `.claude-task-master/`
3. **Agent Wrapper** - Claude Agent SDK `query()` with real-time streaming
4. **Planner** - Planning phase (Read, Glob, Grep tools only)
5. **Work Loop Orchestrator** - Execution loop with task tracking
6. **Logger** - Consolidated `logs/run-{timestamp}.txt`

**State Directory**:
```
.claude-task-master/
├── goal.txt              # User goal
├── criteria.txt          # Success criteria
├── plan.md               # Tasks (markdown checkboxes)
├── state.json            # Machine state
├── progress.md           # Progress summary
├── context.md            # Accumulated learnings
└── logs/
    └── run-*.txt         # Last 10 logs kept
```

## Exit Codes

- **0 (Success)**: Tasks done, cleanup all except logs/, keep last 10 logs
- **1 (Blocked)**: Need intervention, keep everything for resume
- **2 (Interrupted)**: Ctrl+C, keep everything for resume

## Key Implementation Details

### Credentials Loading
- File structure: `{"claudeAiOauth": {accessToken, refreshToken, expiresAt, ...}}`
- `expiresAt` is milliseconds (int), divide by 1000 for datetime
- Agent SDK auto-uses OAuth from credentials file

### Agent SDK Integration
- Use `query()` with `ClaudeAgentOptions(allowed_tools=[], permission_mode="bypassPermissions")`
- Message types: `TextBlock`, `ToolUseBlock`, `ToolResultBlock`, `ResultMessage`
- Change to working dir before query, restore after
- Stream output real-time: 🔧 for tools, ✓ for completion

### Task Management
- Parse `- [ ]` and `- [x]` from plan.md
- Check `_is_task_complete()` before running (skip if [x])
- Mark complete with `_mark_task_complete()`
- Increment `current_task_index` and save state

### CLI Commands
All commands check `state_manager.exists()` first:
- `start`: Initialize and run planning → work loop
- `status`: Show goal, status, session count, options
- `plan`: Display plan.md with markdown rendering
- `logs`: Show last N lines from log file
- `progress`: Display progress.md
- `context`: Display context.md
- `clean`: Remove .claude-task-master/ with confirmation

### Planning Prompt
- Instructs Claude to add `.claude-task-master/` to .gitignore
- Use Read, Glob, Grep to explore codebase
- Create task list with checkboxes
- Define success criteria

## Testing

Test in `tmp/test-project-1/`:
```bash
cd tmp/test-project-1
uv run python -m claude_task_master.cli start "Implement TODO" --max-sessions 3 --no-auto-merge
```

## Important Notes

1. **Always check if tasks already complete** - planning phase might finish some tasks
2. **Real-time output** - stream Claude's thinking and tool use
3. **Log rotation** - auto-keep last 10 logs only
4. **Clean exit** - delete state files on success, keep logs
5. **OAuth credentials** - handle nested JSON structure properly
6. **Working directory** - change dir for queries, always restore
