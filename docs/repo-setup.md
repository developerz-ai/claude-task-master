# Repository Setup Workflow

This guide provides comprehensive documentation for the repository setup workflow in Claude Task Master. This workflow enables AI-driven development environments where repositories can be autonomously cloned, configured, and prepared for development.

## Table of Contents

- [Overview](#overview)
- [Use Cases](#use-cases)
- [Workflow Phases](#workflow-phases)
  - [Phase 1: Clone](#phase-1-clone)
  - [Phase 2: Setup](#phase-2-setup)
  - [Phase 3: Plan](#phase-3-plan)
  - [Phase 4: Work](#phase-4-work)
- [Access Methods](#access-methods)
- [Complete Examples](#complete-examples)
- [Project Type Detection](#project-type-detection)
- [Setup Scripts](#setup-scripts)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

---

## Overview

The repository setup workflow provides a systematic approach to preparing development environments for AI-driven work. It consists of four phases:

1. **Clone** - Clone a git repository to the workspace
2. **Setup** - Automatically configure the development environment
3. **Plan** - Analyze the codebase and create a task plan (optional)
4. **Work** - Execute tasks according to the plan

This workflow is particularly valuable for:
- AI server deployments receiving autonomous work requests
- Setting up multiple projects in isolated environments
- Preparing repositories for immediate development
- Creating reproducible development environments

---

## Use Cases

### AI Developer Servers

Deploy Claude Task Master to servers where it autonomously:
1. Receives work requests via REST API or MCP
2. Clones the target repository to `~/workspace/claude-task-master/{project-name}`
3. Sets up the development environment (dependencies, venv, setup scripts)
4. Plans or executes the requested work
5. Creates pull requests with completed changes

### Multi-Project Coordination

Manage multiple projects simultaneously:
- Each project cloned to isolated directory
- Dependencies installed per-project
- Work coordinated via mailbox messages
- State tracked independently per project

### Development Environment Automation

Quickly prepare repositories for development:
- Clone from GitHub/GitLab/BitBucket
- Auto-detect project type (Python, Node.js, Ruby, etc.)
- Install dependencies and create virtual environments
- Run project-specific setup scripts
- Ready to work without manual configuration

---

## Workflow Phases

### Phase 1: Clone

Clone a git repository to the workspace directory.

**Default Target Directory:**
```
~/workspace/claude-task-master/{project-name}
```

**Via REST API:**

```bash
POST /repo/clone

{
  "url": "https://github.com/user/my-project.git",
  "target_dir": "/home/user/workspace/claude-task-master/my-project",  # Optional
  "branch": "main"  # Optional
}
```

**Via MCP Tools:**

```python
clone_repo(
    url="https://github.com/user/my-project.git",
    target_dir="/home/user/workspace/claude-task-master/my-project",  # Optional
    branch="main"  # Optional
)
```

**Via CLI:**

```bash
# The CLI doesn't have a dedicated clone command
# Use REST API or MCP tools for clone operations
```

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | Yes | - | Git repository URL (HTTPS, SSH, or git protocol) |
| `target_dir` | string | No | `~/workspace/claude-task-master/{repo-name}` | Custom target directory path |
| `branch` | string | No | (repository default) | Branch to checkout after cloning |

**Response:**

```json
{
  "success": true,
  "message": "Repository cloned successfully",
  "repo_url": "https://github.com/user/my-project.git",
  "target_dir": "/home/user/workspace/claude-task-master/my-project",
  "branch": "main"
}
```

**What Happens:**

1. Parent directory is created if it doesn't exist
2. Git repository is cloned using `git clone`
3. Specified branch is checked out (if provided)
4. Ready for setup phase

**Error Handling:**

- Invalid or empty URL → `400 Bad Request`
- Target directory already exists → `400 Bad Request`
- Permission denied on parent directory → `500 Internal Server Error`
- Network error or invalid repository → `500 Internal Server Error`

---

### Phase 2: Setup

Set up the cloned repository for development by installing dependencies and running setup scripts.

**Via REST API:**

```bash
POST /repo/setup

{
  "work_dir": "/home/user/workspace/claude-task-master/my-project"
}
```

**Via MCP Tools:**

```python
setup_repo(
    work_dir="/home/user/workspace/claude-task-master/my-project"
)
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `work_dir` | string | Yes | Path to the cloned repository directory |

**Response:**

```json
{
  "success": true,
  "message": "Repository setup completed successfully",
  "work_dir": "/home/user/workspace/claude-task-master/my-project",
  "steps_completed": [
    "Detected Python project",
    "Created virtual environment at .venv",
    "Installed dependencies with uv",
    "Executed setup script: scripts/setup-hooks.sh"
  ],
  "venv_path": "/home/user/workspace/claude-task-master/my-project/.venv",
  "dependencies_installed": true,
  "setup_scripts_run": ["scripts/setup-hooks.sh"]
}
```

**What Happens:**

1. **Project Type Detection** - Examines files to determine project type (see [Project Type Detection](#project-type-detection))
2. **Virtual Environment Creation** - Creates language-specific virtual environments:
   - Python: `.venv` using `python -m venv` or `uv venv`
   - Node.js: `node_modules` via package manager
   - Ruby: Bundler-managed gems
3. **Dependency Installation** - Installs dependencies from lock files:
   - Python: `requirements.txt`, `pyproject.toml`, `uv.lock`
   - Node.js: `package.json`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`
   - Ruby: `Gemfile`, `Gemfile.lock`
4. **Setup Scripts Execution** - Runs discovered setup scripts (see [Setup Scripts](#setup-scripts))

**Error Handling:**

- Work directory doesn't exist → `404 Not Found`
- Path is not a directory → `400 Bad Request`
- Setup commands fail → `400 Bad Request` (with error details)
- Permission denied → `500 Internal Server Error`

---

### Phase 3: Plan

Analyze the codebase and generate a task plan without executing any work.

**Via REST API:**

```bash
POST /repo/plan

{
  "work_dir": "/home/user/workspace/claude-task-master/my-project",
  "goal": "Add authentication to the API",
  "model": "opus"
}
```

**Via MCP Tools:**

```python
plan_repo(
    work_dir="/home/user/workspace/claude-task-master/my-project",
    goal="Add authentication to the API",
    model="opus"  # Optional: opus, sonnet, haiku
)
```

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `work_dir` | string | Yes | - | Path to the repository directory |
| `goal` | string | Yes | - | The goal or task description (1-10000 chars) |
| `model` | string | No | `opus` | Model to use for planning (opus, sonnet, haiku) |

**Response:**

```json
{
  "success": true,
  "message": "Plan created successfully",
  "work_dir": "/home/user/workspace/claude-task-master/my-project",
  "goal": "Add authentication to the API",
  "plan": "# Task Plan\n\n- [ ] Create auth module with JWT utilities\n- [ ] Add authentication middleware\n- [ ] Update API endpoints with auth checks\n- [ ] Add tests for authentication\n- [ ] Update API documentation",
  "criteria": "## Success Criteria\n\n- [ ] All API endpoints require valid JWT token\n- [ ] Tests pass with 95%+ coverage\n- [ ] Documentation updated\n- [ ] No breaking changes to existing clients",
  "run_id": "plan_20240118_143022"
}
```

**What Happens:**

1. **Codebase Exploration** - Uses read-only tools (Read, Glob, Grep, Bash) to explore the repository
2. **Pattern Analysis** - Identifies existing patterns, architecture, and dependencies
3. **Plan Generation** - Creates a structured task list with markdown checkboxes
4. **Success Criteria Definition** - Defines measurable success criteria
5. **State Persistence** - Saves plan to `.claude-task-master/plan.md` and criteria to `.claude-task-master/criteria.txt`

**Read-Only Tools Used:**

- **Read** - Read specific files
- **Glob** - Find files by pattern
- **Grep** - Search file contents
- **Bash** - Run read-only commands (ls, grep, find, etc.)

**No Changes Made:**

The planning phase is strictly read-only. No files are modified, created, or deleted.

**Error Handling:**

- Work directory doesn't exist → `404 Not Found`
- Goal is empty or too long → `400 Bad Request`
- Task already in progress → `400 Bad Request`
- Credentials not available → `500 Internal Server Error`

**Model Selection:**

- **opus** (recommended) - Best quality planning, deepest analysis
- **sonnet** - Faster planning, good for simple tasks
- **haiku** - Fastest planning, basic analysis

---

### Phase 4: Work

Execute the planned tasks. This phase uses the standard `claudetm start` workflow.

**Via CLI:**

```bash
# Initialize and start work
cd ~/workspace/claude-task-master/my-project
claudetm start "Add authentication to the API" --max-sessions 10

# Or resume existing work
claudetm resume
```

**Via REST API:**

```bash
# Initialize task
POST /task/init
{
  "goal": "Add authentication to the API",
  "model": "opus",
  "auto_merge": true,
  "max_sessions": 10
}

# The work loop runs automatically
# Monitor via GET /status, GET /progress, GET /logs
```

**What Happens:**

1. **Planning** (if not already done) - Creates task plan and success criteria
2. **Work Loop** - Executes tasks sequentially:
   - Make changes to code
   - Run tests
   - Commit changes
   - Push to remote
   - Create pull request
3. **PR Lifecycle** - Handles CI checks, review comments, and merging
4. **Verification** - Runs tests and checks success criteria
5. **Completion** - Reports results and cleans up

See the main [README](../README.md) for detailed information on the work phase.

---

## Access Methods

The repository setup workflow is accessible via three methods:

### 1. REST API

**Best for:**
- Server deployments
- Remote orchestration
- Webhook integrations
- External automation

**Start the API server:**

```bash
claudetm-server --port 8000 --password your-secret
```

**Example:**

```bash
# Clone
curl -X POST http://localhost:8000/repo/clone \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret" \
  -d '{"url": "https://github.com/user/project.git"}'

# Setup
curl -X POST http://localhost:8000/repo/setup \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret" \
  -d '{"work_dir": "/home/user/workspace/claude-task-master/project"}'

# Plan
curl -X POST http://localhost:8000/repo/plan \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret" \
  -d '{
    "work_dir": "/home/user/workspace/claude-task-master/project",
    "goal": "Add feature X"
  }'
```

See [API Reference](./api-reference.md) for complete documentation.

### 2. MCP Tools

**Best for:**
- IDE integration (Cursor, VS Code)
- Conversational workflows
- AI coordination
- Interactive development

**Start the MCP server:**

```bash
claudetm mcp
```

**Configure in IDE:**

```json
{
  "mcpServers": {
    "claude-task-master": {
      "command": "claudetm",
      "args": ["mcp"]
    }
  }
}
```

**Example Usage (in IDE chat):**

```
User: Clone the repository https://github.com/user/project.git

Claude: [Uses clone_repo tool]
Repository cloned successfully to ~/workspace/claude-task-master/project

User: Set it up for development

Claude: [Uses setup_repo tool]
Setup completed. Created .venv and installed dependencies.

User: Plan work for adding feature X

Claude: [Uses plan_repo tool]
I've analyzed the codebase and created a task plan...
```

See [MCP Tools Reference](./mcp-tools.md) for complete documentation.

### 3. CLI (Limited)

The CLI provides indirect access via the standard workflow:

```bash
# Manual clone
git clone https://github.com/user/project.git ~/workspace/claude-task-master/project

# Manual setup (project-specific)
cd ~/workspace/claude-task-master/project
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Plan and work
claudetm start "Add feature X" --max-sessions 10
```

For automated clone and setup, use REST API or MCP tools.

---

## Complete Examples

### Example 1: Python Web Application

**Scenario:** Clone, setup, and plan work for a Python Flask application.

```bash
# 1. Clone repository
curl -X POST http://localhost:8000/repo/clone \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://github.com/example/flask-api.git",
    "branch": "main"
  }'

# Response:
# {
#   "success": true,
#   "target_dir": "/home/user/workspace/claude-task-master/flask-api",
#   "branch": "main"
# }

# 2. Setup development environment
curl -X POST http://localhost:8000/repo/setup \
  -H "Content-Type: application/json" \
  -d '{
    "work_dir": "/home/user/workspace/claude-task-master/flask-api"
  }'

# Response:
# {
#   "success": true,
#   "steps_completed": [
#     "Detected Python project (found pyproject.toml)",
#     "Created virtual environment at .venv",
#     "Installed dependencies with uv sync",
#     "Executed setup script: scripts/setup-hooks.sh"
#   ],
#   "venv_path": "/home/user/workspace/claude-task-master/flask-api/.venv",
#   "dependencies_installed": true,
#   "setup_scripts_run": ["scripts/setup-hooks.sh"]
# }

# 3. Create a plan (analysis only, no changes)
curl -X POST http://localhost:8000/repo/plan \
  -H "Content-Type: application/json" \
  -d '{
    "work_dir": "/home/user/workspace/claude-task-master/flask-api",
    "goal": "Add rate limiting to the API endpoints",
    "model": "opus"
  }'

# Response:
# {
#   "success": true,
#   "plan": "# Task Plan\n\n- [ ] Install Flask-Limiter...",
#   "criteria": "## Success Criteria\n\n- [ ] Rate limits enforced...",
#   "run_id": "plan_20240118_143022"
# }

# 4. Execute the work (separate session)
cd ~/workspace/claude-task-master/flask-api
claudetm start "Add rate limiting to the API endpoints" --max-sessions 10
```

### Example 2: Node.js Application

**Scenario:** Setup a Node.js project using MCP tools from an IDE.

```
User: Clone https://github.com/example/express-app.git to my workspace

Claude: [Calls clone_repo tool]
I've cloned the repository to ~/workspace/claude-task-master/express-app

User: Set it up for development

Claude: [Calls setup_repo tool]
Setup completed! I:
- Detected a Node.js project (found package.json)
- Installed dependencies using npm install
- Ran setup script: scripts/postinstall.sh

The project is ready for development.

User: Create a plan for adding user authentication

Claude: [Calls plan_repo tool]
I've analyzed the Express application and created a comprehensive plan for adding authentication:

## Task Plan

- [ ] Install authentication dependencies (passport, bcrypt, jsonwebtoken)
- [ ] Create user model and database schema
- [ ] Implement authentication middleware
- [ ] Add login and registration routes
- [ ] Update existing routes to require authentication
- [ ] Add tests for authentication flow
- [ ] Update API documentation

## Success Criteria

- [ ] Users can register with email and password
- [ ] Users can login and receive JWT token
- [ ] Protected routes require valid JWT
- [ ] Tests achieve 90%+ coverage
- [ ] No existing functionality broken

The plan is saved to .claude-task-master/plan.md
```

### Example 3: Multi-Project Coordination

**Scenario:** Setup and coordinate work across multiple related projects.

```bash
# Project 1: API Backend
curl -X POST http://localhost:8000/repo/clone \
  -d '{"url": "https://github.com/example/api-backend.git"}'

curl -X POST http://localhost:8000/repo/setup \
  -d '{"work_dir": "/home/user/workspace/claude-task-master/api-backend"}'

# Project 2: Frontend Application
curl -X POST http://localhost:8000/repo/clone \
  -d '{"url": "https://github.com/example/frontend-app.git"}'

curl -X POST http://localhost:8000/repo/setup \
  -d '{"work_dir": "/home/user/workspace/claude-task-master/frontend-app"}'

# Project 3: Shared Library
curl -X POST http://localhost:8000/repo/clone \
  -d '{"url": "https://github.com/example/shared-lib.git"}'

curl -X POST http://localhost:8000/repo/setup \
  -d '{"work_dir": "/home/user/workspace/claude-task-master/shared-lib"}'

# Work on backend (in one terminal)
cd ~/workspace/claude-task-master/api-backend
claudetm start "Add new endpoint" --max-sessions 5

# Work on frontend (in another terminal)
cd ~/workspace/claude-task-master/frontend-app
claudetm start "Consume new endpoint" --max-sessions 5

# Coordinate via mailbox
curl -X POST http://localhost:8000/mailbox/send \
  -d '{
    "content": "Backend endpoint is ready at /api/v2/users",
    "sender": "backend-team",
    "priority": 2
  }'
```

---

## Project Type Detection

The setup phase automatically detects project type by examining indicator files:

### Python Projects

**Indicator Files:**
- `pyproject.toml` (modern Python projects)
- `setup.py` (legacy setup)
- `requirements.txt` (pip dependencies)
- `uv.lock` (uv-managed projects)
- `Pipfile` (pipenv projects)
- `poetry.lock` (poetry projects)

**Setup Actions:**
1. Create virtual environment: `python -m venv .venv` or `uv venv`
2. Install dependencies:
   - If `uv.lock` exists: `uv sync`
   - If `requirements.txt` exists: `pip install -r requirements.txt`
   - If `pyproject.toml` exists: `pip install -e .` or `uv sync`
   - If `Pipfile` exists: `pipenv install`
   - If `poetry.lock` exists: `poetry install`

**Virtual Environment Location:**
- `.venv/` (standard location)

### Node.js Projects

**Indicator Files:**
- `package.json` (all Node.js projects)
- `package-lock.json` (npm)
- `yarn.lock` (yarn)
- `pnpm-lock.yaml` (pnpm)
- `bun.lockb` (bun)

**Setup Actions:**
1. Detect package manager from lock file
2. Install dependencies:
   - `npm`: `npm install`
   - `yarn`: `yarn install`
   - `pnpm`: `pnpm install`
   - `bun`: `bun install`

**Virtual Environment Location:**
- `node_modules/` (standard location)

### Ruby Projects

**Indicator Files:**
- `Gemfile` (bundler-managed projects)
- `Gemfile.lock` (bundler lock file)

**Setup Actions:**
1. Ensure bundler is installed: `gem install bundler`
2. Install dependencies: `bundle install`

**Virtual Environment Location:**
- Managed by bundler (system or project-local gems)

### Other Project Types

Support can be added for:
- **Go**: Detect `go.mod`, run `go mod download`
- **Rust**: Detect `Cargo.toml`, run `cargo build`
- **Java/Maven**: Detect `pom.xml`, run `mvn install`
- **Java/Gradle**: Detect `build.gradle`, run `gradle build`

---

## Setup Scripts

The setup phase automatically discovers and executes setup scripts in priority order:

### Discovery Locations

1. `scripts/setup-hooks.sh` - Git hooks setup
2. `scripts/setup.sh` - General project setup
3. `scripts/install.sh` - Installation script
4. `scripts/bootstrap.sh` - Bootstrap script
5. `setup.sh` - Root-level setup
6. `install.sh` - Root-level install
7. `bootstrap.sh` - Root-level bootstrap
8. `Makefile` (target: `setup` or `install`) - Make-based setup

### Execution Order

Scripts are executed in the order listed above. If multiple scripts exist, all are executed.

### Script Requirements

**Executable Permission:**

Scripts must be executable. The setup phase will attempt to run:

```bash
chmod +x script.sh
./script.sh
```

**Exit Codes:**

- `0` - Success (continue setup)
- Non-zero - Failure (abort setup, return error)

**Best Practices:**

1. Make scripts idempotent (safe to run multiple times)
2. Include error handling and clear output
3. Document what the script does
4. Test scripts in clean environments

### Example Setup Script

```bash
#!/bin/bash
# scripts/setup-hooks.sh

set -e  # Exit on error

echo "Setting up git hooks..."

# Install pre-commit hooks
if command -v pre-commit &> /dev/null; then
    pre-commit install
    echo "✓ Pre-commit hooks installed"
else
    echo "⚠ pre-commit not found, skipping hooks"
fi

# Setup local git config
git config --local core.hooksPath .githooks
echo "✓ Git hooks configured"

echo "Setup complete!"
```

---

## Best Practices

### 1. Use Consistent Directory Structure

Keep all AI-managed projects in the workspace directory:

```
~/workspace/claude-task-master/
├── project-1/
├── project-2/
├── project-3/
└── ...
```

This provides:
- Isolation between projects
- Easy discovery and management
- Consistent path structure

### 2. Always Run Setup After Clone

Even if you plan to work immediately, run the setup phase:

```bash
# Good
curl -X POST /repo/clone ...
curl -X POST /repo/setup ...  # Always setup
curl -X POST /task/init ...

# Bad
curl -X POST /repo/clone ...
curl -X POST /task/init ...  # Missing setup!
```

### 3. Use Plan Phase for Complex Work

For non-trivial tasks, use the plan phase first:

```bash
# Clone and setup
curl -X POST /repo/clone ...
curl -X POST /repo/setup ...

# Plan first (review plan.md)
curl -X POST /repo/plan ...

# Review the plan, then start work
cd ~/workspace/claude-task-master/project
claudetm start "..." --max-sessions 10
```

### 4. Choose Appropriate Model for Planning

**opus** - Complex features, architecture changes
**sonnet** - Standard features, bug fixes
**haiku** - Simple tasks, quick analysis

### 5. Monitor Setup Logs

Setup can fail for various reasons. Check logs:

```bash
# Via API
curl http://localhost:8000/logs?tail=100

# Via CLI (if working locally)
tail -f .claude-task-master/logs/run_*.txt
```

### 6. Handle Setup Failures

If setup fails:

1. Check the error message
2. Review setup logs
3. Fix the issue manually if needed
4. Re-run setup or continue manually

```bash
# If setup fails, you can:
# 1. Fix the issue
cd ~/workspace/claude-task-master/project
source .venv/bin/activate
pip install -r requirements.txt

# 2. Re-run setup via API
curl -X POST /repo/setup ...
```

### 7. Version Control Setup Scripts

Include setup scripts in your repository:

```
my-project/
├── scripts/
│   ├── setup-hooks.sh    # Git hooks
│   ├── setup.sh          # Project setup
│   └── install.sh        # Dependencies
├── pyproject.toml
└── README.md
```

### 8. Use Webhooks for Automation

Configure webhooks to receive notifications:

```bash
# Register webhook for setup events
curl -X POST http://localhost:8000/webhooks \
  -d '{
    "url": "https://hooks.slack.com/...",
    "events": ["run.started", "run.completed"],
    "name": "Setup Notifications"
  }'
```

---

## Troubleshooting

### Clone Failures

**Symptom:** Repository clone fails with error.

**Common Causes:**
1. Invalid or inaccessible repository URL
2. Network connectivity issues
3. Authentication required (private repo)
4. Target directory already exists

**Solutions:**

```bash
# Verify URL
git ls-remote https://github.com/user/project.git

# Check authentication (for private repos)
gh auth status

# Remove existing directory
rm -rf ~/workspace/claude-task-master/project

# Retry with explicit branch
curl -X POST /repo/clone \
  -d '{
    "url": "https://github.com/user/project.git",
    "branch": "main"
  }'
```

### Setup Failures

**Symptom:** Setup phase fails to complete.

**Common Causes:**
1. Missing system dependencies
2. Incompatible Python/Node version
3. Network issues downloading dependencies
4. Setup script failures

**Solutions:**

```bash
# Check Python version
python --version

# Check Node version (for Node projects)
node --version

# Install system dependencies manually
sudo apt-get install build-essential python3-dev

# View detailed setup logs
curl http://localhost:8000/logs?tail=200

# Retry setup after fixes
curl -X POST /repo/setup \
  -d '{"work_dir": "/home/user/workspace/claude-task-master/project"}'
```

### Dependency Installation Failures

**Symptom:** Dependencies fail to install during setup.

**Common Causes:**
1. Incompatible dependency versions
2. Network timeout downloading packages
3. Missing system libraries
4. Corrupted package cache

**Solutions:**

```bash
# Python projects - clear pip cache
rm -rf ~/.cache/pip

# Python projects - upgrade pip
source .venv/bin/activate
pip install --upgrade pip

# Node projects - clear npm cache
npm cache clean --force

# Retry with verbose logging
pip install -r requirements.txt -v
```

### Plan Generation Failures

**Symptom:** Planning phase fails or produces incomplete plan.

**Common Causes:**
1. Large codebase exceeds context limit
2. Missing credentials
3. Ambiguous or overly broad goal
4. Project structure not recognized

**Solutions:**

```bash
# Be more specific with goal
curl -X POST /repo/plan \
  -d '{
    "work_dir": "...",
    "goal": "Add JWT authentication to the /api/users endpoint using the existing AuthService class",
    "model": "opus"
  }'

# Try with different model
curl -X POST /repo/plan \
  -d '{
    "work_dir": "...",
    "goal": "...",
    "model": "sonnet"
  }'

# Check credentials
claudetm doctor
```

### Permission Errors

**Symptom:** Permission denied errors during clone or setup.

**Common Causes:**
1. Insufficient permissions on workspace directory
2. Running as wrong user
3. Parent directory doesn't exist

**Solutions:**

```bash
# Create workspace directory with correct permissions
mkdir -p ~/workspace/claude-task-master
chmod 755 ~/workspace/claude-task-master

# Fix ownership
sudo chown -R $USER:$USER ~/workspace/claude-task-master

# Verify permissions
ls -la ~/workspace/claude-task-master
```

### Multiple Setup Script Failures

**Symptom:** Setup succeeds but some scripts fail.

**Common Causes:**
1. Scripts not executable
2. Scripts expect specific environment
3. Scripts have dependencies not installed

**Solutions:**

```bash
# Make scripts executable
chmod +x scripts/*.sh

# Run scripts manually to debug
cd ~/workspace/claude-task-master/project
./scripts/setup-hooks.sh

# Check script dependencies
cat scripts/setup.sh  # Review requirements
```

---

## See Also

- [REST API Reference](./api-reference.md) - Complete API documentation
- [MCP Tools Reference](./mcp-tools.md) - MCP tools documentation
- [Mailbox Guide](./mailbox.md) - Inter-instance communication
- [Webhooks Guide](./webhooks.md) - Event notifications
- [Main README](../README.md) - General usage and CLI commands

---

**Questions or Issues?**

Visit the [GitHub repository](https://github.com/developerz-ai/claude-task-master) to report issues or contribute improvements.
