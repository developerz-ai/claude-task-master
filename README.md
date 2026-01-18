# Claude Task Master

[![CI](https://github.com/developerz-ai/claude-task-master/actions/workflows/ci.yml/badge.svg)](https://github.com/developerz-ai/claude-task-master/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/developerz-ai/claude-task-master/graph/badge.svg)](https://codecov.io/gh/developerz-ai/claude-task-master)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI version](https://badge.fury.io/py/claude-task-master.svg)](https://badge.fury.io/py/claude-task-master)

Autonomous task orchestration system that keeps Claude working until a goal is achieved.

## Quick Start

```bash
# Install from PyPI
pip install claude-task-master

# Or with uv (recommended)
uv tool install claude-task-master

# Verify setup
claudetm doctor
```

### Upgrading

```bash
# With pip
pip install --upgrade claude-task-master

# With uv
uv tool install claude-task-master --force --reinstall

# Check version
claudetm --version
```

### Run a Task

```bash
cd your-project
claudetm start "Add user authentication with tests"
```

## Overview

Claude Task Master uses the Claude Agent SDK to autonomously work on complex tasks. Give it a goal, and it will:

1. **Plan** - Analyze codebase and create a task list organized by PRs
2. **Execute** - Work through each task, committing and pushing changes
3. **Create PRs** - All work is pushed and submitted as pull requests
4. **Handle CI** - Wait for checks, fix failures, address review comments
5. **Merge** - Auto-merge when approved (configurable)
6. **Verify** - Confirm all success criteria are met

**Core Philosophy**: Claude is smart enough to do the work AND verify it. Task Master keeps the loop going and persists state between sessions.

## Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                         PLANNING                                 │
│  Read codebase → Create task list → Define success criteria     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      WORKING (per task)                          │
│  Make changes → Run tests → Commit → Push → Create PR           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                       PR LIFECYCLE                               │
│  Wait for CI → Fix failures → Address reviews → Merge           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                       VERIFICATION                               │
│  Run tests → Check lint → Verify criteria → Done                │
└─────────────────────────────────────────────────────────────────┘
```

### Work Completion Requirements

Every task must be:
- **Committed** with a descriptive message
- **Pushed** to remote (`git push -u origin HEAD`)
- **In a PR** (`gh pr create ...`)

Work is NOT complete until it's pushed and in a pull request.

## Installation

### Prerequisites

1. **Python 3.10+** - [Install Python](https://www.python.org/downloads/)
2. **Claude CLI** - [Install Claude](https://github.com/anthropics/anthropic-sdk-python) and run `claude` to authenticate
3. **GitHub CLI** - [Install gh](https://cli.github.com/) and run `gh auth login`

### Install Claude Task Master

**Option 1: Using uv (recommended)**

```bash
# Install uv if you haven't already
curl https://astral.sh/uv/install.sh | sh

# Install Claude Task Master
uv sync

# Verify installation
uv run claudetm doctor
```

**Option 2: Using pip**

```bash
# Install from PyPI
pip install claude-task-master

# Verify installation
claudetm doctor
```

**Option 3: Development installation**

```bash
# Clone the repository
git clone https://github.com/developerz-ai/claude-task-master
cd claude-task-master

# Install with development dependencies
pip install -e ".[dev]"

# Run tests
pytest
```

### Initial Setup

Run the doctor command to verify everything is configured:

```bash
claudetm doctor
```

This checks for:
- ✓ Claude CLI credentials at `~/.claude/.credentials.json`
- ✓ GitHub CLI authentication
- ✓ Git configuration
- ✓ Python version compatibility

## Configuration

Claude Task Master uses a config file to override environment variables. This is useful for:
- Using alternative API providers (OpenRouter, etc.)
- Customizing model names
- Setting project-specific settings

### Create Config File

```bash
# Initialize default config
claudetm --init-config

# View current config
claudetm --show-config
```

This creates `.claude-task-master/config.json`:

```json
{
  "version": "1.0",
  "api": {
    "anthropic_api_key": null,
    "anthropic_base_url": "https://api.anthropic.com",
    "openrouter_api_key": null,
    "openrouter_base_url": "https://openrouter.ai/api/v1"
  },
  "models": {
    "sonnet": "claude-sonnet-4-5-20250929",
    "opus": "claude-opus-4-5-20251101",
    "haiku": "claude-haiku-4-5-20251001"
  },
  "git": {
    "target_branch": "main",
    "auto_push": true
  }
}
```

### Environment Variables

The config file sets these environment variables before Python starts:

| Config Key | Environment Variable | Description |
|------------|---------------------|-------------|
| `api.anthropic_api_key` | `ANTHROPIC_API_KEY` | Anthropic API key |
| `api.anthropic_base_url` | `ANTHROPIC_BASE_URL` | API base URL |
| `api.openrouter_api_key` | `OPENROUTER_API_KEY` | OpenRouter API key |
| `api.openrouter_base_url` | `OPENROUTER_BASE_URL` | OpenRouter base URL |
| `models.sonnet` | `CLAUDETM_MODEL_SONNET` | Model for sonnet tier |
| `models.opus` | `CLAUDETM_MODEL_OPUS` | Model for opus tier |
| `models.haiku` | `CLAUDETM_MODEL_HAIKU` | Model for haiku tier |
| `git.target_branch` | `CLAUDETM_TARGET_BRANCH` | Target branch for PRs |

### Using OpenRouter

To use OpenRouter instead of direct Anthropic API:

```json
{
  "api": {
    "openrouter_api_key": "sk-or-v1-xxx",
    "openrouter_base_url": "https://openrouter.ai/api/v1"
  },
  "models": {
    "sonnet": "anthropic/claude-sonnet-4",
    "opus": "anthropic/claude-opus-4",
    "haiku": "anthropic/claude-haiku"
  }
}
```

### Debug Config Loading

```bash
# Enable debug mode to see config loading
CLAUDETM_DEBUG=1 claudetm status
```

## Usage

### CLI Commands

| Command | Description |
|---------|-------------|
| `claudetm start "goal"` | Start a new task |
| `claudetm resume` | Resume a paused task |
| `claudetm status` | Show current status |
| `claudetm plan` | View task list |
| `claudetm progress` | View progress summary |
| `claudetm context` | View accumulated learnings |
| `claudetm logs` | View session logs |
| `claudetm pr` | Show PR status and CI checks |
| `claudetm comments` | Show review comments |
| `claudetm clean` | Clean up task state |
| `claudetm doctor` | Verify system setup |

### Start Options

```bash
claudetm start "Your goal here" [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--model` | Model to use (sonnet, opus, haiku) | sonnet |
| `--auto-merge/--no-auto-merge` | Auto-merge PRs when ready | True |
| `--max-sessions` | Limit number of sessions | unlimited |
| `--pause-on-pr` | Pause after creating PR | False |

### Common Workflows

```bash
# Simple task with auto-merge
claudetm start "Add factorial function to utils.py with tests"

# Complex task with manual review
claudetm start "Refactor auth system" --model opus --no-auto-merge

# Limited sessions to prevent runaway
claudetm start "Fix bug in parser" --max-sessions 5

# Monitor progress
watch -n 5 'claudetm status'
```

## Examples & Use Cases

Check the [examples/](./examples/) directory for detailed walkthroughs:

### Quick Examples

```bash
# Add a simple function
claudetm start "Add a factorial function to utils.py with tests"

# Fix a bug
claudetm start "Fix authentication timeout in login.py" --no-auto-merge

# Feature development
claudetm start "Add dark mode toggle to settings" --model opus

# Refactoring
claudetm start "Refactor API client to use async/await" --max-sessions 5

# Documentation
claudetm start "Add API documentation and examples"
```

### Available Guides

1. **[Basic Usage](./examples/01-basic-usage.md)** - Simple tasks and fundamentals
2. **[Feature Development](./examples/02-feature-development.md)** - Building complete features
3. **[Bug Fixing](./examples/03-bug-fixing.md)** - Debugging and fixing issues
4. **[Code Refactoring](./examples/04-refactoring.md)** - Improving code structure
5. **[Testing](./examples/05-testing.md)** - Adding test coverage
6. **[Documentation](./examples/06-documentation.md)** - Documentation and examples
7. **[CI/CD Integration](./examples/07-cicd.md)** - GitHub Actions workflows
8. **[Advanced Workflows](./examples/08-advanced-workflows.md)** - Complex scenarios

## Troubleshooting

### Credentials & Setup

#### "Claude CLI credentials not found"
```bash
# Run the Claude CLI to authenticate
claude

# Verify credentials were saved
ls -la ~/.claude/.credentials.json

# Run doctor to check setup
claudetm doctor
```

#### "GitHub CLI not authenticated"
```bash
# Authenticate with GitHub
gh auth login

# Verify authentication
gh auth status
```

### Common Issues

#### Task appears stuck or not progressing

```bash
# Check current status
claudetm status

# View detailed logs
claudetm logs -n 100

# If truly stuck, you can interrupt and resume
# Press Ctrl+C, then:
claudetm resume
```

#### PR creation fails

```bash
# Verify you're in a git repository
git status

# Verify remote is set up
git remote -v

# Check if a PR already exists
gh pr list

# Run doctor to diagnose
claudetm doctor
```

#### Tests or linting failures

The system will handle failures and retry. To debug:

```bash
# Check the latest logs
claudetm logs

# View progress summary
claudetm progress

# See what Claude learned from errors
claudetm context
```

#### Clean up and restart

```bash
# Safe cleanup - removes state but keeps logs
claudetm clean

# Force cleanup without confirmation
claudetm clean -f

# Start fresh task
claudetm start "Your new goal"
```

### Performance Tips

1. **Use the right model**:
   - `opus` for complex tasks (default)
   - `sonnet` for balanced speed/quality
   - `haiku` for simple tasks

2. **Limit sessions to prevent infinite loops**:
   ```bash
   claudetm start "Task" --max-sessions 10
   ```

3. **Manual review for critical changes**:
   ```bash
   claudetm start "Task" --no-auto-merge
   ```

4. **Monitor in another terminal**:
   ```bash
   watch -n 5 'claudetm status'
   ```

### Debug Mode

View detailed execution information:

```bash
# Show recent log entries
claudetm logs -n 200

# View current plan and progress
claudetm plan
claudetm progress

# See accumulated context from previous sessions
claudetm context
```

## Architecture

The system follows SOLID principles with strict Single Responsibility:

### Core Components

| Component | Responsibility |
|-----------|----------------|
| **Credential Manager** | OAuth credential loading from `~/.claude/.credentials.json` |
| **State Manager** | Persistence to `.claude-task-master/` directory |
| **Agent Wrapper** | Claude Agent SDK interactions with streaming output |
| **Planner** | Planning phase with read-only tools (Read, Glob, Grep, Bash) |
| **Orchestrator** | Main execution loop and workflow stage management |
| **GitHub Client** | PR creation, CI monitoring, comment handling |
| **PR Cycle Manager** | Full PR lifecycle (create → CI → reviews → merge) |
| **Context Accumulator** | Builds learnings across sessions |

### Workflow Stages

```
working → pr_created → waiting_ci → ci_failed → waiting_reviews → addressing_reviews → ready_to_merge → merged
```

Each stage has specific handlers that determine when to transition to the next stage.

## State Directory

```
.claude-task-master/
├── goal.txt              # Original user goal
├── criteria.txt          # Success criteria
├── plan.md               # Task list with checkboxes
├── state.json            # Machine-readable state
├── progress.md           # Progress summary
├── context.md            # Accumulated learnings
└── logs/
    └── run-{timestamp}.txt    # Full log (kept on success)
```

## Exit Codes

- **0 (Success)**: All tasks completed, criteria met. State cleaned up, logs preserved.
- **1 (Blocked)**: Task cannot proceed, needs human intervention or error occurred.
- **2 (Interrupted)**: User pressed Ctrl+C, state preserved for resume.

## Development

### Testing

```bash
pytest                    # Run all tests
pytest -v                 # Verbose output
pytest -k "test_name"     # Run specific tests
```

### Linting & Formatting

```bash
ruff check .              # Lint
ruff format .             # Format
mypy .                    # Type check
```

## License

MIT
