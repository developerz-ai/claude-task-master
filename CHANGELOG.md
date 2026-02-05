# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.10] - 2026-02-05

### Added
- **`--prs` flag to limit pull requests**: New CLI flag to constrain the number of PRs created
  - Injected into planning prompt to guide task organization
  - Claude plans work to fit within the specified PR limit
  - Example: `claudetm start "Add auth" --prs 1` → Everything in one PR
  - Available in CLI, REST API, and MCP tools
  - Supports dynamic configuration via `max_prs` parameter

### Changed
- **Dependency updates**: Updated to latest stable versions
  - claude-agent-sdk: 0.1.27 → 0.1.30
  - rich: 13.0.0 → 14.3.2
  - ruff: 0.3.0 → 0.15.0
  - hypothesis: 6.100.0 → 6.151.5
  - mcp: 1.0.0 → 1.26.0
  - fastapi: 0.100.0 → 0.128.1

### Fixed
- **Enum inheritance**: Updated string enums to use `StrEnum` for Python 3.11+ compatibility
- **CI optimization**: Removed Docker build from PR checks (now only runs on releases)
- **CI concurrency**: Added cancel-in-progress to avoid redundant CI runs

## [0.1.9] - 2026-02-01

### Changed
- **Bump claude-agent-sdk to >=0.1.27**: Fixes automatic token refresh that was failing with "Token refresh failed: Bad request - the refresh token may be malformed" error. Users no longer need to manually open Claude CLI to refresh tokens.

## [0.1.8] - 2026-01-24

### Added
- **Coding style guide generation**: Automatically generates `coding-style.md` from CLAUDE.md
  - Extracts development workflow, code conventions, and project-specific requirements
  - Injects coding style into planning and work prompts for consistent code quality
  - Preserved across runs to save tokens (not deleted on success)
  - Uses Opus model for high-quality extraction

### Changed
- Planning and work prompts now respect coding requirements from CLAUDE.md
- Coding style guide (~600 words) provides concise guidance for agents

## [0.1.7] - 2026-01-24

### Fixed
- **Merge conflict prevention**: Agent now rebases onto target branch before pushing PRs
  - Fetches latest changes from target branch and rebases before push
  - Includes detailed conflict resolution instructions for the agent
  - Prevents merge conflicts when other PRs are merged during long-running tasks

### Changed
- **Configurable target branch**: Rebase instructions now use `config.git.target_branch`
  instead of hardcoded "main"
  - Supports repos using different default branches (master, develop, etc.)
  - Configurable via config file or `CLAUDETM_TARGET_BRANCH` env var

## [0.1.6] - 2026-01-23

### Changed
- Improved planning prompt with web research workflow guidance
- Clarified WebFetch can only fetch URLs from search results or user-provided URLs
- Added recommended workflow: WebSearch first, then WebFetch for full content
- Documented PDF support for technical documentation in WebFetch

## [0.1.5] - 2026-01-22

### Changed
- Release alignment: includes all v0.1.4 features properly tagged and published

### Fixed
- Git tag alignment with published CHANGELOG entries

## [0.1.4] - 2026-01-22

### Added

#### Webhook Events - Enhanced Event System
- Extended webhook event system with new event types:
  - `run.started` - Emitted when orchestrator starts execution
  - `run.completed` - Emitted when orchestrator finishes (success, failure, or blocked state)
  - `status.changed` - Emitted when task status transitions between states (pending → in_progress → completed)
  - `ci.passed` - Emitted when CI checks pass for a PR
  - `ci.failed` - Emitted when CI checks fail for a PR
  - `plan.updated` - Emitted when plan is updated via mailbox/API or plan updater
- New event dataclasses: `CIPassedEvent`, `CIFailedEvent`, `PlanUpdatedEvent`, `StatusChangedEvent`, `RunStartedEvent`, `RunCompletedEvent`
- Updated `EventType` enum with complete event type coverage
- Comprehensive webhook event documentation in `docs/webhooks.md` with payload examples

#### AI Developer Workflow - Repository Setup
- **New MCP Tools** for AI developer environments:
  - `clone_repo(url, target_dir, branch)` - Clone git repository to `~/workspace/claude-task-master/{project-name}`
  - `setup_repo(work_dir)` - Run dependency installation, create venv, execute setup scripts
  - `plan_repo(work_dir, goal)` - Plan-only mode that analyzes codebase and generates task plan without execution
- **New REST API Endpoints** for repository management:
  - `POST /repo/clone` - Clone a git repository with configuration
  - `POST /repo/setup` - Setup cloned repository for development
  - `POST /repo/plan` - Plan-only mode: analyze codebase and generate task plan
- New Pydantic models: `CloneRepoRequest`, `SetupRepoRequest`, `PlanRepoRequest`, `SetupRepoResult`, `PlanRepoResult`
- New routes module `src/claude_task_master/api/routes_repo.py` for repository endpoints
- Comprehensive repository setup guide (`docs/repo-setup.md`) describing the AI developer workflow: clone → setup → plan → work

#### Documentation Enhancements
- Complete webhook events documentation in `docs/webhooks.md` with all 7+ event types and payload formats
- Comprehensive repository setup workflow guide in `docs/repo-setup.md`
- Updated `docs/api-reference.md` with new `/repo/clone`, `/repo/setup`, `/repo/plan` endpoint documentation
- Updated `docs/mcp-tools.md` with new `clone_repo`, `setup_repo`, `plan_repo` tool documentation
- Enhanced `CLAUDE.md` project instructions with:
  - New webhook events in the Webhook Events section
  - New MCP tools in the MCP Tools section
  - New REST API endpoints in the API Endpoints section

#### Testing & Quality Assurance
- Unit tests for all new webhook event types in `tests/webhooks/test_events.py`
- Integration tests for webhook emissions in `tests/core/test_orchestrator_webhooks.py`
- Tests for new MCP tools in `tests/mcp/test_tools_repo.py`
- Tests for new REST API endpoints in `tests/api/test_routes_repo.py`
- Full test suite passing with 100% coverage of new features
- Comprehensive type checking with mypy
- Code formatting and linting with ruff

### Changed
- Webhook event system now includes lifecycle events (run.started, run.completed)
- Task lifecycle tracking now includes status.changed events for granular monitoring
- CI/CD workflow integration now emits separate ci.passed and ci.failed events instead of combined events

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- N/A

## [0.1.3] - 2026-01-19

Release tag alignment - all features documented under v0.1.2 are now properly included in this tagged release.

## [0.1.2] - 2025-01-18

### Added

#### REST API & Server
- REST API foundation with FastAPI including `/health`, `/status`, `/start`, `/pause`, `/resume`, `/stop` endpoints
- Unified `claudetm-server` command that runs REST API and MCP server together with shared authentication
- REST API webhook management endpoints: `/webhooks` CRUD operations and `/webhooks/test` for testing
- REST API configuration and control endpoints (`/config`, `/control`)
- REST API status endpoint with full session, task, and webhook information
- `--rest-port`, `--mcp-port` arguments for configuring server ports

#### Authentication & Security
- Password-based authentication module with bcrypt hashing via `passlib[bcrypt]`
- FastAPI `PasswordAuthMiddleware` supporting `Authorization: Bearer <password>` header
- Password authentication for REST API with `--password` CLI argument and `CLAUDETM_PASSWORD` environment variable
- Password authentication for MCP server SSE and streamable-http network transports with Bearer token
- Unified authentication across REST API, MCP server, and webhook endpoints
- Health endpoint bypasses authentication to allow monitoring without credentials

#### Webhooks
- Complete webhook infrastructure with event system supporting 8 event types:
  - `task.started`, `task.completed`, `task.failed`
  - `pr.created`, `pr.merged`
  - `session.started`, `session.completed`, `system.error`
- WebhookClient with HMAC-SHA256 signature generation for secure webhook delivery
- WebhookConfig Pydantic model with URL, secret, and event filter configuration
- CLI arguments `--webhook-url` and `--webhook-secret` for `claudetm start` command
- Environment variables `CLAUDETM_WEBHOOK_URL` and `CLAUDETM_WEBHOOK_SECRET` support
- Webhook integration with task orchestrator lifecycle (emits events at key points)
- Webhook test endpoint to verify configuration before deploying

#### Docker & Containerization
- Multi-stage Dockerfile with builder and runtime stages for production-ready container
- `.dockerignore` file for efficient Docker build context
- `docker-compose.yml` with local development setup including volume mounts for:
  - Project directory (`/app/project`)
  - Claude credentials (`/root/.claude`)
  - Configuration volumes
- Docker build verification in GitHub Actions CI workflow
- GitHub Actions workflow for publishing Docker images to GitHub Container Registry (GHCR)
- Multi-architecture support (linux/amd64, linux/arm64) for Docker images
- Automatic image tagging with version numbers and `latest` tag on releases

#### CLI Features
- `fix-pr` command for iterative PR fixing with automatic retries and conflict resolution
- `pause` and `stop` CLI entry points for workflow control
- Skip already-merged PRs in workflow stages to prevent re-processing

#### Documentation
- Comprehensive Docker usage guide (`docs/docker.md`) with:
  - Installation instructions using Docker images
  - Quick start examples
  - Volume mounting instructions for project directory and Claude credentials
  - Environment variable configuration reference
  - Docker Compose examples for production deployment
- Detailed authentication guide (`docs/authentication.md`) with:
  - Password-based auth flow explanation
  - curl examples for authenticated REST API requests
  - MCP client configuration examples
  - Webhook HMAC signature verification examples (Python, Node.js)
- Complete API reference (`docs/api-reference.md`) with:
  - All REST API endpoints documented
  - Request/response examples for each endpoint
  - Status codes and error handling
  - Authentication requirements
- Comprehensive webhooks documentation (`docs/webhooks.md`) with:
  - Event types and payload formats
  - Webhook configuration guide
  - HMAC signature verification
  - Examples for common webhook receivers (Slack, Discord, custom HTTP servers)
- Updated README with:
  - Docker installation option
  - Updated architecture section with server diagram
  - Links to comprehensive documentation

### Changed
- REST API health endpoint is now accessible without authentication
- Tool output now displays relative paths instead of absolute paths for better readability
- MCP server security warning now mentions password authentication requirement
- Enhanced logging to show authentication status on API startup

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- Fixed timeout issues in test_run_verification_failed test
- Resolved mypy type errors in test files
- Fixed PR merge flow to require actual PR creation before proceeding
- Fixed workflow to properly handle already-merged PRs

### Security
- Password authentication required for REST API and MCP server
- HMAC-SHA256 signatures for webhook delivery verification
- Environment variable support for sensitive credentials
- bcrypt hashing for password storage in configuration
- Updated SECURITY.md documentation with authentication security measures

## [0.1.1] - 2025-01-17

### Added
- Core Control Layer (Foundation) with pause, resume, stop, and update config tools
- MCP server control tools for workflow management
- REST API foundation with FastAPI
- CLI entry points for pause/stop commands
- Enhanced README with authentication instructions and upgrade guide

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- Implemented missing `/config` and `/control` API endpoints
- Added comprehensive status endpoint tests

### Security
- N/A

## [0.1.0] - 2025-01-16

### Added
- Initial project setup with autonomous task orchestration
- Core components: Credential Manager, State Manager, Agent Wrapper
- Planner module with read-only exploration (Read, Glob, Grep tools)
- Work Loop Orchestrator with task tracking and session management
- CLI commands: start, status, plan, logs, progress, context, clean, doctor
- State persistence in `.claude-task-master/` directory
- Real-time streaming output with tool use indicators
- Log rotation (keeps last 10 logs)
- OAuth credential management from `~/.claude/.credentials.json`
- Exit code handling (0: success, 1: blocked, 2: interrupted)

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- N/A

[Unreleased]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.10...HEAD
[0.1.10]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.9...v0.1.10
[0.1.9]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.8...v0.1.9
[0.1.8]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/developerz-ai/claude-task-master/releases/tag/v0.1.0
