# Contributing to Claude Task Master

Thank you for your interest in contributing to Claude Task Master! This document provides guidelines and information for contributors.

## Getting Started

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager
- Git
- GitHub CLI (`gh`) for PR management

### Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/your-org/claude-task-master-py.git
   cd claude-task-master-py
   ```

2. Install dependencies:
   ```bash
   uv sync --all-extras
   ```

3. Verify setup:
   ```bash
   uv run claudetm doctor
   ```

## Development Workflow

### Running Tests

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/core/test_agent.py

# Run with coverage report
uv run pytest --cov=claude_task_master --cov-report=html
```

### Code Quality

We use several tools to maintain code quality:

```bash
# Linting
uv run ruff check .

# Formatting
uv run ruff format .

# Type checking
uv run mypy src/
```

Run all checks before submitting a PR:
```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src/ && uv run pytest
```

### Code Style Guidelines

- **Maximum file length**: 500 lines of code per file
- **Single Responsibility**: Each module should have one reason to change
- **Type hints**: All functions must have type annotations
- **Docstrings**: Use Google-style docstrings for public APIs
- **Line length**: 100 characters maximum

### Commit Messages

Follow conventional commits format:

```
type: Brief description (50 chars max)

- What changed
- Why it was needed

Co-Authored-By: Your Name <email@example.com>
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `test`: Adding or updating tests
- `refactor`: Code refactoring
- `chore`: Maintenance tasks

## Pull Request Process

1. **Create a branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make changes** and commit frequently

3. **Run all checks**:
   ```bash
   uv run ruff check . && uv run ruff format . && uv run mypy src/ && uv run pytest
   ```

4. **Push and create PR**:
   ```bash
   git push -u origin HEAD
   gh pr create --title "feat: Your feature" --body "Description of changes"
   ```

5. **Address review feedback** promptly

6. **Wait for CI** to pass before requesting merge

### PR Guidelines

- Keep PRs focused and small when possible
- Include tests for new functionality
- Update documentation as needed
- Link to relevant issues
- Respond to review comments within 48 hours

## Project Structure

```
claude-task-master-py/
├── src/claude_task_master/
│   ├── cli.py              # CLI commands
│   ├── core/               # Core functionality
│   │   ├── agent.py        # Agent wrapper
│   │   ├── orchestrator.py # Work loop
│   │   ├── planner.py      # Planning phase
│   │   └── state.py        # State management
│   ├── github/             # GitHub integration
│   └── mcp/                # MCP server
├── tests/                  # Test files
├── examples/               # Usage examples
└── docs/                   # Documentation
```

## Testing Guidelines

### Test Structure

- One test file per module
- Use pytest fixtures for setup
- Group related tests in classes
- Name tests descriptively: `test_function_scenario_expected_result`

### Coverage Requirements

- Minimum 80% coverage required
- All new features need tests
- Edge cases should be tested

### Example Test

```python
"""Tests for the example module."""

import pytest
from claude_task_master.core.example import ExampleClass


class TestExampleClass:
    """Tests for ExampleClass."""

    def test_method_returns_expected_value(self):
        """Test that method returns the expected value."""
        instance = ExampleClass()
        result = instance.method()
        assert result == "expected"

    def test_method_raises_on_invalid_input(self):
        """Test that method raises ValueError for invalid input."""
        instance = ExampleClass()
        with pytest.raises(ValueError, match="Invalid input"):
            instance.method(invalid=True)
```

## Reporting Issues

### Bug Reports

Include:
- Python version and OS
- Steps to reproduce
- Expected vs actual behavior
- Error messages and stack traces

### Feature Requests

Include:
- Clear description of the feature
- Use case and motivation
- Proposed implementation (optional)

## Questions?

- Open a [GitHub Discussion](https://github.com/your-org/claude-task-master-py/discussions)
- Check existing issues and PRs

Thank you for contributing!
