# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial release preparation

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

[Unreleased]: https://github.com/anthropics/claude-task-master-py/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/anthropics/claude-task-master-py/releases/tag/v0.1.0
