# Security Policy

## Reporting Security Issues

**Please do not open public issues for security vulnerabilities.**

If you discover a security vulnerability, please email security@example.com with:
- Description of the vulnerability
- Steps to reproduce (if applicable)
- Potential impact
- Suggested fix (if available)

We will acknowledge your email within 48 hours and provide a timeline for addressing the issue.

## Security Measures

### Code Security Scanning

This project uses the following security tools to maintain code quality and security:

#### CodeQL Analysis
- **Enabled**: Yes
- **Frequency**:
  - On every push to `main` or `master` branches
  - On every pull request
  - Weekly scheduled scan (Sunday 2 AM UTC)
- **Purpose**: Detect potential security vulnerabilities and code quality issues using GitHub's CodeQL
- **Results**: Published to [GitHub Security tab](https://github.com/[owner]/[repo]/security)

#### Ruff Linter
- **Enabled**: Yes
- **Checks**: Code quality, style, and common issues
- **Frequency**: On every push and pull request

#### Type Checking
- **Tool**: mypy
- **Enabled**: Yes
- **Frequency**: On every push and pull request

### Dependencies

- Dependencies are managed via `uv`
- Production dependencies are minimal and pinned in `pyproject.toml`
- Development dependencies include security-focused linters and type checkers

### Python Version Support

- Minimum: Python 3.11
- Testing: Python 3.11 and 3.12
- CodeQL: Python 3.11

## Best Practices

1. **Keep Dependencies Updated**: Regularly update dependencies to patch security issues
2. **Use Type Hints**: All code uses type hints to catch potential type-related bugs
3. **Code Review**: All changes go through code review via pull requests
4. **Automated Testing**: Comprehensive test suite with 80%+ coverage requirement
5. **Authentication**: Uses OAuth for Anthropic Claude API integration

## Security Considerations

### Credential Handling

The project handles OAuth credentials securely:
- Credentials are stored in `~/.claude/.credentials.json` (user's home directory)
- Credentials are never logged or exposed in output
- Access tokens use OAuth refresh token flow

### Data Privacy

- No persistent storage of API request/response content
- Logs are cleaned automatically (last 10 kept)
- User data is never sent to external services except Anthropic's API

## CI/CD Security

- GitHub Actions uses official, verified actions
- No custom shell scripts for sensitive operations
- Secrets are managed through GitHub Secrets
- CodeQL results are uploaded to GitHub's security infrastructure

## Compliance

This project aims to follow:
- OWASP Top 10 principles
- Python Security Best Practices
- GitHub Security Guidelines
