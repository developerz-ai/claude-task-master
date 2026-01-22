# Claude Task Master

[![CI](https://github.com/developerz-ai/claude-task-master/actions/workflows/ci.yml/badge.svg)](https://github.com/developerz-ai/claude-task-master/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/developerz-ai/claude-task-master/graph/badge.svg)](https://codecov.io/gh/developerz-ai/claude-task-master)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI version](https://badge.fury.io/py/claude-task-master.svg)](https://badge.fury.io/py/claude-task-master)

Autonomous task orchestration system that keeps Claude working until a goal is achieved.

## Quick Start

### Installation

**Option 1: Using uv (recommended)**

```bash
# Install with uv
uv tool install claude-task-master
```

**Option 2: Using pip**

```bash
# Install from PyPI
pip install claude-task-master
```

**Option 3: Using Docker**

```bash
# Pull the official Docker image from GitHub Container Registry
docker pull ghcr.io/developerz-ai/claude-task-master:latest

# Run with Docker (requires Claude credentials mounted)
docker run -d \
  --name claudetm \
  -p 8000:8000 \
  -v ~/.claude:/home/claudetm/.claude:ro \
  -v $(pwd):/app/project \
  -v ~/.gitconfig:/home/claudetm/.gitconfig:ro \
  -v ~/.config/gh:/home/claudetm/.config/gh:ro \
  ghcr.io/developerz-ai/claude-task-master:latest
```

See [Docker Deployment Guide](./docs/docker.md) for detailed Docker setup, volume mounts, and configuration options.

### Authentication

Before using claudetm, you need to authenticate with Claude:

```bash
# Run Claude CLI and login (this saves credentials that claudetm will use)
claude
/login

# Verify claudetm can access credentials
claudetm doctor
```

**For Docker users:** Ensure your `~/.claude/.credentials.json` exists before running the container, as Claude Task Master needs OAuth credentials to function.

### Upgrading

**With uv:**
```bash
uv tool install claude-task-master --force --reinstall
```

**With pip:**
```bash
pip install --upgrade claude-task-master
```

**With Docker:**
```bash
# Pull the latest image
docker pull ghcr.io/developerz-ai/claude-task-master:latest

# Restart your container with the new image
docker-compose up -d
```

**Check version:**
```bash
claudetm --version
```

### Run a Task

**Using the CLI:**
```bash
cd your-project
claudetm start "Add user authentication with tests"
```

**Using Docker:**
```bash
# Task execution is handled through the unified server
# Create tasks via the REST API or MCP interface
curl -H "Authorization: Bearer password" \
     http://localhost:8000/tasks -X POST \
     -d '{"goal": "Add user authentication"}'
```

## Overview

Claude Task Master uses the Claude Agent SDK to autonomously work on complex tasks. Give it a goal, and it will:

1. **Plan** - Analyze codebase and create a task list organized by PRs
2. **Execute** - Work through each task, committing and pushing changes
3. **Create PRs** - All work is pushed and submitted as pull requests
4. **Handle CI** - Wait for checks, fix failures, address review comments
5. **Merge** - Auto-merge when approved (configurable)
6. **Verify** - Confirm all success criteria are met
7. **Adapt** - Accept dynamic plan updates via mailbox while working

**Core Philosophy**: Claude is smart enough to do the work AND verify it. Task Master keeps the loop going and persists state between sessions.

### Key Features

- **Autonomous Execution** - Runs until goal is achieved or needs human input
- **PR-Based Workflow** - All work flows through pull requests for review
- **CI Integration** - Handles CI failures and review comments together
- **Mailbox System** - Receive dynamic plan updates while working (via REST API, MCP, or CLI)
- **Multi-Instance Coordination** - Multiple instances can communicate via mailbox
- **State Persistence** - Survives interruptions, resumes where it left off

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

## Documentation

Complete documentation for all features and deployment options:

| Guide | Description |
|-------|-------------|
| **[Docker Deployment](./docs/docker.md)** | Docker installation, configuration, volume mounts, and production deployment |
| **[Authentication](./docs/authentication.md)** | Password-based authentication for REST API, MCP server, and webhooks |
| **[REST API Reference](./docs/api-reference.md)** | Complete REST API endpoint documentation with examples |
| **[Webhooks](./docs/webhooks.md)** | Webhook events, payload formats, HMAC signature verification, and integration examples |
| **[Mailbox System](./docs/mailbox.md)** | Inter-instance communication, dynamic plan updates, and multi-instance coordination |

## Usage

### CLI Commands

| Command | Description |
|---------|-------------|
| `claudetm start "goal"` | Start a new task |
| `claudetm resume` | Resume a paused task |
| `claudetm resume "message"` | Update plan with message, then resume |
| `claudetm status` | Show current status |
| `claudetm plan` | View task list |
| `claudetm progress` | View progress summary |
| `claudetm context` | View accumulated learnings |
| `claudetm logs` | View session logs |
| `claudetm pr` | Show PR status and CI checks |
| `claudetm comments` | Show review comments |
| `claudetm clean` | Clean up task state |
| `claudetm doctor` | Verify system setup |
| `claudetm mailbox` | Show mailbox status |
| `claudetm mailbox send "msg"` | Send message to mailbox |
| `claudetm mailbox clear` | Clear pending messages |

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

# Resume with a change request (updates plan first)
claudetm resume "Also add input validation to the forms"

# Send message to mailbox via REST API
curl -X POST http://localhost:8000/mailbox/send \
  -H "Content-Type: application/json" \
  -d '{"content": "Prioritize security fixes", "priority": 2}'
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

## AI Developer Workflow

Claude Task Master includes built-in support for repository cloning and setup, enabling an AI-driven development environment. This is particularly useful for:

- **AI Server Deployments** - Deploy Claude Task Master to servers and have it autonomously clone and setup projects
- **Development Environment Setup** - Automatically configure repositories for local development
- **Multi-Project Coordination** - Manage multiple projects simultaneously, each in isolated directories
- **Continuous AI Development** - Receive work requests, setup projects, implement tasks, all autonomously

### Repo Setup Workflow

The repo setup workflow consists of three phases:

1. **Clone** - Clone a git repository to `~/workspace/claude-task-master/{project-name}`
2. **Setup** - Automatically install dependencies, create virtual environments, run setup scripts
3. **Plan or Work** - Either analyze the project and create a plan, or immediately start working on tasks

### Clone a Repository

**Via REST API:**
```bash
curl -X POST http://localhost:8000/repo/clone \
  -H "Content-Type: application/json" \
  -d '{
    "repo_url": "https://github.com/example/my-project.git",
    "project_name": "my-project"
  }'
```

**Via MCP Tools (IDE Integration):**
```
Claude: Clone the repository https://github.com/example/my-project.git
→ Uses clone_repo tool to clone to ~/workspace/claude-task-master/my-project
```

### Setup a Cloned Repository

After cloning, setup installs dependencies and prepares the project for development:

**Via REST API:**
```bash
curl -X POST http://localhost:8000/repo/setup \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "my-project"
  }'
```

**Via MCP Tools:**
```
Claude: Set up the project my-project for development
→ Uses setup_repo tool to configure and prepare the repository
```

The setup phase:
- Detects project type (Python, Node.js, Ruby, etc.)
- Installs package manager if needed (uv, npm, pip, bundler, etc.)
- Creates virtual environments (venv, node_modules, etc.)
- Runs setup scripts if present (setup.sh, Makefile, scripts/setup-hooks.sh, etc.)
- Installs dependencies from lock files (requirements.txt, package.json, Gemfile, etc.)

### Plan a Repository (Analysis Only)

Analyze a project and generate a task plan without executing work:

**Via REST API:**
```bash
curl -X POST http://localhost:8000/repo/plan \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "my-project",
    "goal": "Add authentication to the application"
  }'
```

**Via MCP Tools:**
```
Claude: Plan the task "Add authentication" for project my-project
→ Uses plan_repo tool to analyze and generate a task plan
```

This phase creates a plan in `.claude-task-master/plan.md` without executing any tasks, allowing review before work begins.

### Complete AI Developer Workflow Example

A full end-to-end workflow:

```bash
# 1. Clone a repository
curl -X POST http://localhost:8000/repo/clone \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/example/myapp.git", "project_name": "myapp"}'

# 2. Setup the project for development
curl -X POST http://localhost:8000/repo/setup \
  -H "Content-Type: application/json" \
  -d '{"project_name": "myapp"}'

# 3. Plan the work (optional - just analyze)
curl -X POST http://localhost:8000/repo/plan \
  -H "Content-Type: application/json" \
  -d '{"project_name": "myapp", "goal": "Add user authentication with OAuth"}'

# 4. Or start work directly with a goal
curl -X POST http://localhost:8000/task/init \
  -H "Content-Type: application/json" \
  -d '{"project_dir": "~/workspace/claude-task-master/myapp", "goal": "Add user authentication with OAuth"}'
```

### Directory Structure

When using the repo setup workflow, projects are organized as follows:

```
~/workspace/claude-task-master/
├── my-project/
│   ├── .git/
│   ├── src/
│   ├── .claude-task-master/      # State directory (auto-created by claudetm)
│   │   ├── goal.txt
│   │   ├── plan.md
│   │   ├── state.json
│   │   └── logs/
│   └── ...
├── another-project/
│   └── ...
```

### Use Cases

**1. Server-Based AI Development Platform**

Deploy Claude Task Master to a server with git credentials and have it:
- Clone repositories on demand
- Setup development environments automatically
- Execute work assignments from a job queue
- Report results via webhooks

```bash
# Server startup
docker run -d \
  -p 8000:8000 \
  -v ~/.claude:/root/.claude:ro \
  -v ~/.gitconfig:/root/.gitconfig:ro \
  -v ~/.config/gh:/root/.config/gh:ro \
  -v ~/workspace:/root/workspace \
  ghcr.io/developerz-ai/claude-task-master:latest

# External system sends work
curl http://ai-dev-server:8000/repo/clone -d '{"repo_url": "...", "project_name": "..."}'
curl http://ai-dev-server:8000/repo/setup -d '{"project_name": "..."}'
curl http://ai-dev-server:8000/task/init -d '{"project_dir": "...", "goal": "..."}'
```

**2. Local Development Workspace Management**

Setup a local workspace where Claude helps manage multiple projects:

```bash
# Initialize workspace
mkdir -p ~/workspace/claude-task-master
cd ~/workspace/claude-task-master

# Clone and setup multiple projects
claudetm repo clone https://github.com/org/api-server api-server
claudetm repo setup api-server

claudetm repo clone https://github.com/org/web-client web-client
claudetm repo setup web-client

# Work on individual projects
cd api-server
claudetm start "Add rate limiting to API endpoints"

cd ../web-client
claudetm start "Implement dark mode toggle"
```

**3. Continuous Integration as AI Development**

Integrate with CI/CD to have Claude automatically work on issues:

```bash
# GitHub Action or external trigger
curl http://localhost:8000/repo/clone \
  -d '{"repo_url": "'$GITHUB_REPOSITORY'", "project_name": "repo"}'

curl http://localhost:8000/repo/setup \
  -d '{"project_name": "repo"}'

curl http://localhost:8000/task/init \
  -d '{"project_dir": "~/workspace/claude-task-master/repo", "goal": "'$ISSUE_TITLE'"}'

# Results reported via webhook callback
```

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

### Server Architecture

When running with the unified server (`claudetm-server`), the following components work together:

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Claude Task Master Server                       │
│                                                                       │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐             │
│  │  REST API    │   │  MCP Server  │   │   Webhooks   │             │
│  │  (FastAPI)   │   │  (FastMCP)   │   │   (httpx)    │             │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘             │
│         │                  │                  │                      │
│         └──────────────────┼──────────────────┘                      │
│                            │                                         │
│                    ┌───────▼───────┐                                 │
│                    │ Auth Module   │                                 │
│                    │ (Password)    │                                 │
│                    └───────────────┘                                 │
└─────────────────────────────────────────────────────────────────────┘

Docker Container:
┌─────────────────────────────────────────────────────────────────────┐
│  claudetm-server                                                     │
│                                                                       │
│  Volumes:                                                            │
│  - /app/project → project directory                                 │
│  - /root/.claude → Claude credentials (~/.claude)                   │
│                                                                       │
│  Env: CLAUDETM_PASSWORD, CLAUDETM_WEBHOOK_URL, ...                   │
└─────────────────────────────────────────────────────────────────────┘
```

**Server Features:**
- **REST API** - Create and manage tasks, view status, manage webhooks
- **MCP Server** - Claude editor integration for native IDE support
- **Webhooks** - Send notifications on task events with HMAC verification
- **Unified Authentication** - Single password protects all three interfaces
- **Docker Ready** - Multi-arch image published to GitHub Container Registry

For detailed Docker deployment, see [Docker Deployment Guide](./docs/docker.md).
For authentication details, see [Authentication Guide](./docs/authentication.md).

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
├── mailbox.json          # Pending messages for plan updates
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
