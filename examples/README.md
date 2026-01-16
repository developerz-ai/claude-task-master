# Claude Task Master Examples

This directory contains practical examples and usage patterns for Claude Task Master.

## Quick Start Examples

### 1. Simple Task
```bash
claudetm start "Add a hello world function to utils.py"
```

### 2. Feature Development
```bash
claudetm start "Add dark mode toggle to the settings page" --model opus
```

### 3. Bug Fix
```bash
claudetm start "Fix authentication timeout issue in login.py" --no-auto-merge
```

### 4. Refactoring
```bash
claudetm start "Refactor API client to use async/await" --max-sessions 5 --pause-on-pr
```

## Examples

1. **[Basic Usage](./01-basic-usage.md)** - Getting started with simple tasks
2. **[Feature Development](./02-feature-development.md)** - Building new features from scratch
3. **[Bug Fixing](./03-bug-fixing.md)** - Debugging and fixing issues
4. **[Code Refactoring](./04-refactoring.md)** - Improving existing code
5. **[Testing](./05-testing.md)** - Adding tests to your codebase
6. **[Documentation](./06-documentation.md)** - Generating and updating docs
7. **[CI/CD Integration](./07-cicd.md)** - Working with GitHub Actions
8. **[Advanced Workflows](./08-advanced-workflows.md)** - Complex multi-task scenarios

## Notebooks

- **[Orchestrator-Workers Workflow](./orchestrator-workers.ipynb)** - Pattern for breaking down tasks and running them in parallel using worker LLMs

## Common Patterns

### Resume After Interruption
```bash
# Task was interrupted (Ctrl+C or Escape)
claudetm resume
```

### Check Progress
```bash
claudetm status    # Current status
claudetm plan      # View task list
claudetm progress  # Human-readable summary
claudetm logs      # View execution logs
```

### Clean Up
```bash
claudetm clean     # Prompts for confirmation
claudetm clean -f  # Force clean without prompt
```

## Model Selection

Choose based on your needs:

- **opus** (default): Most capable, best for complex tasks
- **sonnet**: Balanced speed and intelligence
- **haiku**: Fastest, good for simple tasks

```bash
claudetm start "Your task" --model sonnet
```

## Auto-merge vs Manual Review

### Auto-merge (default)
```bash
claudetm start "Add feature X"
# PR will be automatically merged when CI passes
```

### Manual review
```bash
claudetm start "Add feature X" --no-auto-merge
# PR stays open for your review
```

### Pause for review
```bash
claudetm start "Add feature X" --pause-on-pr
# Task pauses after PR creation, resume when ready
```

## Session Limits

Prevent infinite loops by limiting sessions:

```bash
claudetm start "Complex task" --max-sessions 10
# Stops after 10 work sessions
```

## Checkpointing (Experimental)

Enable file checkpointing for safe rollbacks:

```bash
claudetm start "Risky refactor" --checkpointing
# Can rollback changes if things go wrong
```

## Troubleshooting

### Check System Setup
```bash
claudetm doctor
# Verifies credentials, GitHub CLI, git config
```

### View CI Status
```bash
claudetm ci-status           # Recent workflow runs
claudetm ci-logs            # Failed run logs
claudetm pr-status 123      # PR #123 status
claudetm pr-comments 123    # Review comments
```

## Best Practices

1. **Start Small**: Begin with simple tasks to understand the workflow
2. **Clear Goals**: Provide specific, actionable goals
3. **Monitor Progress**: Use `status` and `plan` commands regularly
4. **Review PRs**: Even with auto-merge, review what Claude produces
5. **Clean State**: Run `clean` after completing tasks to start fresh
6. **Check Logs**: If something fails, `logs` shows detailed execution

## Real-World Examples

See the individual example files for detailed walkthroughs:

- Adding authentication system
- Implementing API endpoints
- Setting up testing infrastructure
- Migrating to new framework
- Performance optimization
- Security vulnerability fixes
