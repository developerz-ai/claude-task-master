# CLAUDE.md

Project instructions for Claude Code when working with Claude Task Master.

## Project Overview

Autonomous task orchestration system that uses Claude Agent SDK to keep Claude working until a goal is achieved. Uses OAuth credentials from `~/.claude/.credentials.json` for authentication.

**Core Philosophy**: Claude is smart enough to do work AND verify it. Task master keeps the loop going and persists state.

### Key Capabilities

- **Autonomous Execution** - Runs until goal achieved or needs human input
- **PR-Based Workflow** - All work flows through pull requests for review
- **CI/CD Integration** - Handles CI failures and review comments together in one step
- **Mailbox System** - Accept dynamic plan updates while working (REST API, MCP, or CLI)
- **Multi-Instance Coordination** - Multiple claudetm instances can communicate via mailbox
- **State Persistence** - Survives interruptions, resumes where it left off
- **Resume with Message** - Update the plan mid-execution with `claudetm resume "message"`

## Installation

### Global Install (Recommended for usage)
```bash
# Install globally via uv tools
uv tool install /path/to/claude-task-master

# Or reinstall after changes
uv tool install --force --reinstall /path/to/claude-task-master

# Verify installation
claudetm doctor
```

### Development Install (For contributing)
```bash
# Clone and setup
uv sync --all-extras             # Install dependencies in .venv
./scripts/setup-hooks.sh         # Install git pre-commit hooks
uv run claudetm doctor           # Check system (runs from .venv)
```

## Quick Start

```bash
# Usage (after global install)
cd <project-dir>
claudetm start "Your task here" --max-sessions 10
claudetm start "Add feature" --prs 1         # Limit to 1 PR
claudetm start "Implement API" --prs 3 -n 10 # Max 3 PRs, 10 sessions
claudetm status           # Check progress
claudetm plan             # View task list
claudetm clean -f         # Clean state

# Or with uv run (development mode)
uv run claudetm start "Your task here"
```

## Development

```bash
pytest                    # Run tests
ruff check . && ruff format .  # Lint & format
mypy .                    # Type check
```

## Releasing

```bash
# 1. Update version in all places:
#    - pyproject.toml (version = "X.Y.Z")
#    - src/claude_task_master/__init__.py (__version__ = "X.Y.Z")
#    - CHANGELOG.md (add entry, update links at bottom)

# 2. Commit and tag
git add -A && git commit -m "chore: Release vX.Y.Z"
git tag vX.Y.Z
git push origin main --tags

# 3. CI publishes to PyPI automatically on tag push
# 4. Install from PyPI after release:
uv tool install claude-task-master --force --reinstall
```

## Architecture

**Components** (Single Responsibility):
1. **Credential Manager** - OAuth from `~/.claude/.credentials.json` (nested `claudeAiOauth` structure)
2. **State Manager** - Persistence to `.claude-task-master/`
3. **Agent Wrapper** - Claude Agent SDK `query()` with real-time streaming
4. **Planner** - Planning phase (read-only tools)
5. **Plan Updater** - Updates existing plans with change requests (for `resume "message"`)
6. **Work Loop Orchestrator** - Execution loop with task tracking, mailbox checks
7. **Mailbox** - Inter-instance communication for dynamic plan updates
8. **PR Context Manager** - CI failures + review comments fetched together
9. **Logger** - Consolidated `logs/run-{timestamp}.txt`

**Tool Configurations by Phase**:
| Phase | Tools | Purpose |
|-------|-------|---------|
| PLANNING | Read, Glob, Grep, WebFetch, WebSearch | Explore codebase + research web for documentation, output plan as TEXT (orchestrator saves to plan.md) |
| VERIFICATION | Read, Glob, Grep, Bash | Run tests/lint to verify success criteria |
| WORKING | All tools | Implement tasks with full access |

**Task Complexity Levels** (for dynamic model routing):
| Complexity | Tag | Model | Use Case |
|------------|-----|-------|----------|
| CODING | `[coding]` | Opus | Complex implementation tasks, new features, intricate logic |
| QUICK | `[quick]` | Haiku | Simple fixes, configuration changes, small tweaks |
| GENERAL | `[general]` | Sonnet | Tests, documentation, moderate refactoring, balanced tasks |
| DEBUGGING_QA | `[debugging-qa]` | Sonnet 1M | CI failures, bug tracing, visual QA, log analysis (1M context) |

When uncertain, default to `[coding]` (uses Opus, most capable).

**State Directory**:
```
.claude-task-master/
├── goal.txt              # User goal
├── criteria.txt          # Success criteria
├── plan.md               # Tasks (markdown checkboxes)
├── state.json            # Machine state
├── progress.md           # Progress summary
├── context.md            # Accumulated learnings
├── coding-style.md       # Coding style guide (generated from CLAUDE.md)
├── mailbox.json          # Pending messages for plan updates
├── logs/
│   └── run-*.txt         # Last 10 logs kept
└── pr-{number}/          # PR-specific context
    ├── ci/*.txt          # CI failure logs
    └── comments/*.txt    # Review comments
```

## Exit Codes

- **0 (Success)**: Tasks done, cleanup all except logs/ and coding-style.md, keep last 10 logs
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

### Work Completion Requirements
**A task is NOT complete until:**
1. Changes are committed with descriptive message
2. Branch is pushed to remote (`git push -u origin HEAD`)
3. PR is created (`gh pr create ...`)

The work prompt enforces this - agents must report both commit hash AND PR URL.

### CLI Commands
All commands check `state_manager.exists()` first:
- `start`: Initialize and run planning → work loop
- `resume`: Resume paused task, optionally with message to update plan first
- `status`: Show goal, status, session count, options
- `plan`: Display plan.md with markdown rendering
- `logs`: Show last N lines from log file
- `progress`: Display progress.md
- `context`: Display context.md
- `clean`: Remove .claude-task-master/ with confirmation
- `mailbox`: Show mailbox status
- `mailbox send "msg"`: Send message to mailbox
- `mailbox clear`: Clear pending messages

### Mailbox System
- Messages stored in `.claude-task-master/mailbox.json`
- Checked after each task completion by orchestrator
- Multiple messages merged with priority ordering (urgent → low)
- Merged message triggers plan update via `PlanUpdater`
- REST: `POST /mailbox/send`, `GET /mailbox`, `DELETE /mailbox`
- MCP: `send_message`, `check_mailbox`, `clear_mailbox` tools

### Resume with Message
- `claudetm resume "change"` updates plan before resuming
- Uses `PlanUpdater` to integrate change request into existing plan
- Preserves completed tasks, modifies pending tasks as needed

### PR Limit (--prs flag)
- `--prs N` limits the maximum number of pull requests that can be created
- Injected into planning prompt to guide task organization
- Claude plans work to fit within the PR limit by grouping tasks intelligently
- Examples:
  - `claudetm start "Add auth" --prs 1` → Everything in one PR
  - `claudetm start "Build dashboard" --prs 3` → Max 3 PRs
- Default: unlimited PRs
- Useful for keeping changes focused and manageable

### Coding Style Generation
- Before planning, generates `coding-style.md` if it doesn't exist
- Analyzes `CLAUDE.md` and convention files to extract:
  - Development workflow (TDD, test-first patterns)
  - Code style conventions (naming, formatting)
  - Project-specific requirements
- Concise guide (~600 words) injected into planning and work prompts
- Preserved across runs (not deleted on success) to save tokens
- Uses Opus for high-quality extraction

### Planning Prompt
- Instructs Claude to add `.claude-task-master/` to .gitignore
- Use Read, Glob, Grep to explore codebase
- Create task list with checkboxes
- Define success criteria
- Includes coding style guide for task planning

## Testing

Test in `tmp/test-project-1/`:
```bash
cd tmp/test-project-1
uv run claudetm start "Implement TODO" --max-sessions 3 --prs 2 --no-auto-merge
```

## Code Style

- **Max 500 LOC per file** - split larger files following SRP/SOLID
- **Single Responsibility** - one reason to change per module

### CI + Comments Combined
- When CI fails, both CI logs AND PR comments are fetched together
- Prevents two-step fixes (CI first, then comments)
- Single work session addresses all feedback at once
- `PRContextManager.save_ci_failures()` automatically calls `save_pr_comments()`

### Webhook Events
The system emits the following webhook events that can be registered at `/webhooks`:

**Run Lifecycle**:
- `run.started` - Emitted when orchestrator starts execution
- `run.completed` - Emitted when orchestrator finishes (success, failure, or blocked state)

**Task Status**:
- `status.changed` - Emitted when task status transitions between states (pending → in_progress → completed)

**CI/CD**:
- `ci.passed` - Emitted when CI checks pass for a PR
- `ci.failed` - Emitted when CI checks fail for a PR

**Plan Updates**:
- `plan.updated` - Emitted when plan is updated via mailbox/API or plan updater

Each webhook event includes:
- `event_id`: Unique identifier for the event
- `event_type`: The event type (one of above)
- `timestamp`: When the event occurred
- `data`: Event-specific payload (varies by event type)

### API Endpoints (REST)
Server runs on port 8000 by default (`claudetm-server`):

**Task Management**:
- `POST /task/init` - Create a new task
- `GET /status` - Get orchestrator status

**Mailbox** (Dynamic Plan Updates):
- `POST /mailbox/send` - Send message to mailbox
- `GET /mailbox` - Check mailbox status
- `DELETE /mailbox` - Clear mailbox

**Control**:
- `POST /control/stop` - Stop orchestrator
- `POST /control/resume` - Resume paused or blocked task

**Webhooks**:
- `GET /webhooks` - List webhooks
- `POST /webhooks` - Register webhook
- `DELETE /webhooks/{id}` - Delete webhook

**Repo Setup** (AI Developer Workflow):
- `POST /repo/clone` - Clone a git repository to `~/workspace/claude-task-master/{project-name}`
- `POST /repo/setup` - Setup cloned repository (install dependencies, create venv, run setup scripts)
- `POST /repo/plan` - Plan-only mode: analyze codebase and generate task plan without executing

**File Operations**:
- `DELETE /coding-style` - Delete the coding-style.md file from the state directory

### MCP Tools
Available via IDE integration:

**Task Management**:
- `get_status` - Get task status
- `pause_task` - Pause current task
- `stop_task` - Stop current task
- `resume_task` - Resume paused or blocked task

**Mailbox** (Dynamic Plan Updates):
- `send_message` - Send message to mailbox
- `check_mailbox` - Check mailbox status
- `clear_mailbox` - Clear mailbox

**Repo Setup** (AI Developer Workflow):
- `clone_repo` - Clone a git repository to `~/workspace/claude-task-master/{project-name}`
- `setup_repo` - Setup cloned repository (install dependencies, create venv, run setup scripts)
- `plan_repo` - Plan-only mode: analyze codebase and generate task plan without executing

**File Operations**:
- `delete_coding_style` - Delete the coding-style.md file from the state directory

## Workflow Integration

### Complete Work Loop

```
┌─────────────────────────────────────────────────────────────────┐
│                         PLANNING                                 │
│  Read codebase → Create task list → Define success criteria     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      WORKING (per task)                          │
│  Make changes → Run tests → Commit → Push → Create PR           │
│                              ↓                                   │
│                      Check Mailbox ←── Messages from REST/MCP   │
│                              ↓                                   │
│              (If messages: Update plan, continue work)          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                       PR LIFECYCLE                               │
│  Wait for CI → Fix failures + comments → Merge                  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                       VERIFICATION                               │
│  Run tests → Check lint → Verify criteria → Done                │
└─────────────────────────────────────────────────────────────────┘
```

### Dynamic Plan Updates

The orchestrator supports mid-execution plan updates via:

1. **CLI Resume with Message**: `claudetm resume "Add rate limiting to API"`
2. **REST API**: `POST /mailbox/send` with message content
3. **MCP Tools**: `send_message` tool from IDE integration

Messages are processed after each task completes. Multiple messages are merged with priority ordering (urgent → low) before updating the plan.

## Important Notes

1. **Always check if tasks already complete** - planning phase might finish some tasks
2. **Real-time output** - stream Claude's thinking and tool use
3. **Log rotation** - auto-keep last 10 logs only
4. **Clean exit** - delete state files on success, keep logs
5. **OAuth credentials** - handle nested JSON structure properly
6. **Working directory** - change dir for queries, always restore
7. **Mailbox check** - orchestrator checks mailbox after each task completion
8. **CI + Comments** - fetched together to handle in one step
9. **Message priority** - 0=low, 1=normal, 2=high, 3=urgent
10. **Plan preservation** - completed tasks preserved when plan updates occur
