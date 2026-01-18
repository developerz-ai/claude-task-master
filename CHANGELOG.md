# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- N/A

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

[Unreleased]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/developerz-ai/claude-task-master/releases/tag/v0.1.0
