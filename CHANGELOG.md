# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.27] - 2026-02-24

### Changed
- **Bump claude-agent-sdk to >=0.1.40**: Updated from 0.1.39 to latest SDK version

## [0.1.26] - 2026-02-23

### Changed
- **Bump claude-agent-sdk to >=0.1.39**: Updated from 0.1.36 to latest SDK version

## [0.1.25] - 2026-02-17

### Changed
- **Upgrade to Claude Sonnet 4.6**: Default sonnet model updated from `claude-sonnet-4-5-20250929` to `claude-sonnet-4-6`
  - Sonnet 4.5 is no longer available; Sonnet 4.6 is the replacement
  - 1M token context window now available in beta
  - Same pricing: $3/$15 per MTok
- **Bump claude-agent-sdk to >=0.1.36**: Updated to latest SDK version

## [0.1.24] - 2026-02-13

### Fixed
- **Increase SDK buffer size to 5MB**: Added `max_buffer_size=5*1024*1024` to all `ClaudeAgentOptions` calls to prevent `CLIJSONDecodeError` on large files ([SDK issue #98](https://github.com/anthropics/claude-agent-sdk-python/issues/98))
- **Disable hooks globally**: Set `self.hooks = {}` (empty dict, not None) to prevent "Stream closed" errors from hook callbacks in Claude Code v2.1.39+

## [0.1.23] - 2026-02-12

### Refactored
- **Simplified credential manager**: Removed manual token refresh logic - now handled by Claude Agent SDK
  - Removed `refresh_access_token()` method (84 lines)
  - Removed `_save_credentials()` method (16 lines)
  - Removed `httpx` dependency from credentials module
  - Reduced from 140 to 99 lines (29% reduction)
  - Credential manager now only loads and validates credentials from disk
  - Token refresh is fully automated by the Claude SDK/binary
  - Updated documentation in CLAUDE.md to clarify SDK handles refresh
  - Removed obsolete test files: `test_credential_manager_refresh.py`, `test_credential_manager_save.py`
  - Updated integration tests to match new behavior
  - All 4,634 tests pass with 95.65% coverage on credentials.py

## [0.1.22] - 2026-02-11

### Enhanced
- **Test pattern extraction in coding-style.md**: Coding style generation now discovers and documents test patterns
  - Finds E2E/integration test locations automatically (`**/e2e/**/*.spec.ts`, `**/*.test.ts`)
  - Extracts test naming conventions, run commands, and example files to follow
  - Critical for `[debugging-qa]` tasks - workers now know exactly where to write tests
  - Increased coding style limit from 600 to 800 words to accommodate test patterns
  - Planning prompt emphasizes test patterns from coding-style.md for debugging-qa tasks

- **Improved `[debugging-qa]` guidance**: Clarified debugging-qa workflow and emphasize automated tests
  - Explicit workflow: 1) Manual test to find issues → 2) Fix bugs → 3) Write integration tests → 4) Verify
  - Emphasizes both manual exploration (finds UX issues) AND automated tests (prevents regressions)
  - Context sublists now reference test patterns from coding-style.md
  - Examples show complete flow from manual testing to automated test code

## [0.1.21] - 2026-02-11

### Changed
- **Dependency updates**: Updated all dependencies to latest stable versions
  - claude-agent-sdk: 0.1.28 → 0.1.35
  - typer: 0.21.1 → 0.22.0
  - fastapi: 0.128.2 → 0.128.7
  - hypothesis: 6.151.5 → 6.151.6
  - bcrypt: relaxed pin from `<4.1.0` to `<5.0.0` (now resolves to 4.3.0)
  - pydantic: bumped minimum to >=2.12.0
  - httpx: bumped minimum to >=0.28.0
  - uvicorn: bumped minimum to >=0.40.0
  - pytest: bumped minimum to >=9.0.0
  - pytest-cov: bumped minimum to >=7.0.0
  - pytest-asyncio: bumped minimum to >=1.3.0
  - mypy: bumped minimum to >=1.19.0
- Added `requirements.txt` with pinned versions for reproducible installs

## [0.1.20] - 2026-02-11

### Added
- **`[debugging-qa]` complexity level** (#93): New task complexity for CI failures, bug tracing, visual QA, and log analysis
  - Routes to Sonnet with 1M context window for deep analysis of large logs and traces
  - New `DEBUGGING_QA` enum value in `TaskComplexity`
  - Updated planning prompts with `[debugging-qa]` tag documentation
  - Config support for `debugging_qa` model and context window settings
  - Comprehensive test coverage for new complexity level

## [0.1.19] - 2026-02-08

### Fixed
- **Stronger CI log warnings with explicit bad examples**: Agents were still reading all log files despite v0.1.18 prompts
  - Added "⚠️ CRITICAL" warning in intro (first thing agents see)
  - Shows explicit BAD examples with ❌ marks of what NOT to do
  - Moved CI workflow above file list so it can't be missed
  - Explicit prohibition: "NEVER spawn tasks to read all logs"
  - Stronger language: "NEVER READ ALL FILES" instead of "DO NOT"
  - Warning now appears in 3 places: intro, file section, and examples

## [0.1.18] - 2026-02-08

### Fixed
- **More concise CI debugging prompts**: Simplified workflow instructions to prevent agents from reading all log files
  - Added explicit `ls` step as first action to see file count before searching
  - Condensed CI debugging section from 20+ lines to 10 lines
  - Simplified PR review feedback workflow from 6 steps to 5 steps
  - More direct language emphasizing the correct workflow: ls → Grep → Read specific files
  - Same safety features and information, 50% less text to parse

## [0.1.17] - 2026-02-08

### Fixed
- **Context overflow from CI logs** (#92): Prevent "Prompt is too long" fatal errors during CI debugging
  - Changed log splitting from line-based (500/file) to character-based (20KB/file)
  - Ensures predictable file sizes (~5,000 tokens) instead of unpredictable 30KB+ files
  - Added explicit warnings in work prompts: "⚠️ DO NOT read all log files at once"
  - Enhanced prompts with step-by-step Grep instructions and concrete examples
  - Prevents agents from reading all log files in parallel (which caused 443KB context overflow)
  - Updated tests for character-based splitting (29/29 pass, 98.26% coverage)

## [0.1.16] - 2026-02-08

### Fixed
- **Task timing always displayed**: Fixed timing not showing for states created before v0.1.15
  - Always display timing even when `task_start_time` is None
  - Uses `session_duration` as fallback for backward compatibility
  - Ensures `[claudetm HH:MM:SS] Task #N took X.X minutes` always shown
- **Enhanced CI log error reporting**: Added detailed error logging for troubleshooting
  - Logs repository name and run ID before downloading
  - Shows job count when logs successfully downloaded
  - Includes full exception tracebacks for debugging
  - Helps identify gh CLI, API, and download failures

## [0.1.15] - 2026-02-07

### Added
- **Task and PR timing metrics** (#91): Track and log timing for tasks and PRs
  - Task timing: Logs how long each task takes from start to completion
  - PR timing: Logs total time, active work time, and CI wait time
  - Format: `[TIMING] Task #N completed in Xm Ys`
  - Format: `[TIMING] PR #N merged - Total: Xm, Active work: Xm, CI wait: Xm`
  - Supports both text and JSON log formats
  - Timing logs always written regardless of log level

### Fixed
- **CI log download bug** (#91): Fixed field name mismatch preventing CI logs from being downloaded
  - Changed `detailsUrl` to `url` to match actual GitHub API response
  - Resolves "Could not extract run ID from check details" error
  - Added debug logging showing sample check URLs when extraction fails
  - Ensures complete timing metrics across all PR creation paths and resume operations

### Testing
- **9 new tests** for timing functionality
- **Updated tests** to use correct GitHub API field names
- All tests passing

## [0.1.14] - 2026-02-07

### Added
- **Complete CI log downloads** (#90): New `CILogDownloader` class that downloads full logs from only failed jobs
  - Downloads complete logs (no 50-line truncation)
  - Gets logs for ONLY failed jobs (not all jobs)
  - Splits into 500-line chunks for AI readability
  - Organized as `.claude-task-master/pr-{N}/ci/{Job_Name}/1.log, 2.log, ...`
  - No ZIP files, no temp file cleanup needed

### Changed
- **CI log structure**: Logs now saved in chunked format (`ci/{Job}/1.log`) instead of single files
- **Extract run ID from check details**: More reliable than using latest run on branch
- **Exclude cancelled jobs**: Only download logs for actual failures, not intentionally cancelled jobs
- **Preserve original job names**: Display "Backend Tests" instead of "Backend_Tests"

### Fixed
- **Get errors at end of logs**: Previous implementation only showed first 50 lines (setup), missing actual errors at the end
- **Stderr bytes handling**: Properly decode stderr before using in error messages
- **Scope issues**: Initialize paths outside try blocks to avoid NameError
- **Silent failures**: Raise error if all log downloads fail instead of returning empty dict
- **Better error messages**: Warn when checks fail but no GitHub Actions logs available (external checks)

### Testing
- **29 new tests** for CILogDownloader class
- **Updated 93 existing tests** for new chunked log structure
- All tests passing

## [0.1.13] - 2026-02-06

### Added
- **CLI commands for PR status and review comments** (#87): New `claudetm pr-status` and `claudetm pr-comments` commands for inspecting PR state from the terminal
- **Task context sublists (file references)** (#86): Tasks in plan.md can now include file reference sublists for better context tracking

### Fixed
- **Clean up remaining minor TODOs**: Resolved leftover TODO items across the codebase

### Testing
- **Comprehensive PR count tracking tests** (#88): Added thorough test coverage for PR count tracking in webhook events

## [0.1.12] - 2026-02-06

### Fixed
- **Downgrade claude-agent-sdk to <0.1.29**: Pin SDK to v0.1.28 (CLI v2.1.30) to avoid
  "Stream closed" hook callback errors introduced in v0.1.29's new hook events
  (`SubagentStop`, `Notification`, `PermissionRequest`). These hooks cause noisy but
  non-fatal `Error in hook callback hook_0: Stream closed` errors on every tool call
  when using `bypassPermissions` mode. See [claude-agent-sdk-python issue](https://github.com/anthropics/claude-agent-sdk-python/issues/).

### Changed
- **CI optimization**: Use 2vcpu runners for all CI jobs (tests are single-threaded)

## [0.1.11] - 2026-02-05

### Changed
- **Upgrade to Claude Opus 4.6**: Default opus model updated from `claude-opus-4-5-20251101` to `claude-opus-4-6`
  - 1M token context window now available in beta (use `context-1m-2025-08-07` beta header)
  - 128K max output tokens (up from 64K)
  - Adaptive thinking support (Opus-only feature)
  - Same pricing: $5/$25 per MTok, premium $10/$37.50 for >200K input
- **Configurable context windows**: New `context_windows` section in config.json
  - Defaults to 200K (standard) for all models
  - Tier 4+ users can set to 1000000 (1M) for Opus and Sonnet
- **Dependency updates**: Updated all dependencies to latest stable versions

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

[Unreleased]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.27...HEAD
[0.1.27]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.26...v0.1.27
[0.1.26]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.25...v0.1.26
[0.1.25]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.24...v0.1.25
[0.1.24]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.23...v0.1.24
[0.1.23]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.22...v0.1.23
[0.1.22]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.21...v0.1.22
[0.1.21]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.20...v0.1.21
[0.1.20]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.19...v0.1.20
[0.1.19]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.18...v0.1.19
[0.1.18]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.17...v0.1.18
[0.1.17]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.16...v0.1.17
[0.1.16]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.15...v0.1.16
[0.1.15]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.14...v0.1.15
[0.1.14]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.13...v0.1.14
[0.1.13]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.12...v0.1.13
[0.1.12]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.11...v0.1.12
[0.1.11]: https://github.com/developerz-ai/claude-task-master/compare/v0.1.10...v0.1.11
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
