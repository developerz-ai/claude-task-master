# Claude Task Master

[![CI](https://github.com/sebyx07/claude-task-master-py/actions/workflows/ci.yml/badge.svg)](https://github.com/sebyx07/claude-task-master-py/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/sebyx07/claude-task-master-py/graph/badge.svg)](https://codecov.io/gh/sebyx07/claude-task-master-py)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI version](https://badge.fury.io/py/claude-task-master.svg)](https://badge.fury.io/py/claude-task-master)

Autonomous task orchestration system that keeps Claude working until a goal is achieved.

## Overview

Claude Task Master uses the Claude Agent SDK to autonomously work on complex tasks by:

- Breaking down goals into actionable task lists
- Executing tasks using appropriate tools (Read, Write, Edit, Bash, etc.)
- Creating and managing GitHub pull requests
- Waiting for CI checks and addressing review comments
- Iterating until all tasks are complete and success criteria are met

**Core Philosophy**: Claude is smart enough to do the work AND verify its own work. The task master just keeps the loop going and persists state between sessions.

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
git clone https://github.com/sebyx07/claude-task-master-py
cd claude-task-master-py

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

## Usage

### Start a new task

```bash
# With uv
uv run claudetm start "Your goal here"

# Or if installed
claudetm start "Your goal here"
```

Options:
- `--model`: Choose model (sonnet, opus, haiku) - default: sonnet
- `--auto-merge/--no-auto-merge`: Auto-merge PRs when ready - default: True
- `--max-sessions`: Limit number of sessions
- `--pause-on-pr`: Pause after creating PR for manual review

### Resume a paused task

```bash
claudetm resume
```

### Check status

```bash
claudetm status    # Current status
claudetm plan      # View task list
claudetm progress  # Progress summary
claudetm logs      # View logs
claudetm context   # View accumulated learnings
```

### PR management

```bash
claudetm pr         # Show PR status and CI checks
claudetm comments   # Show review comments
```

### Cleanup

```bash
claudetm clean      # Clean up task state
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

- **Credential Manager**: OAuth credential loading and refresh
- **State Manager**: All persistence to `.claude-task-master/` directory
- **Agent Wrapper**: Claude Agent SDK interactions
- **Planner**: Initial planning phase with read-only tools
- **Work Loop Orchestrator**: Main execution loop
- **GitHub Integration**: PR creation, CI monitoring, comment handling
- **PR Cycle Manager**: Full PR lifecycle management
- **Logger**: Consolidated logging per run
- **Context Accumulator**: Builds learnings across sessions

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
