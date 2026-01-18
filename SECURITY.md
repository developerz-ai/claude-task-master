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
5. **Authentication**: Uses OAuth for Anthropic Claude API integration AND password-based auth for network services

## Security Considerations

### Credential Handling

The project handles credentials securely:

**OAuth Credentials (Claude API):**
- Credentials are stored in `~/.claude/.credentials.json` (user's home directory)
- Credentials are never logged or exposed in output
- Access tokens use OAuth refresh token flow

**Password Authentication (Network Services):**
- Passwords are hashed using bcrypt with 12 rounds (cost factor)
- Only the hash is stored/configured via `CLAUDETM_PASSWORD_HASH`
- Plaintext passwords (`CLAUDETM_PASSWORD`) are only for development
- Password verification uses constant-time comparison to prevent timing attacks

### Data Privacy

- No persistent storage of API request/response content
- Logs are cleaned automatically (last 10 kept)
- User data is never sent to external services except Anthropic's API
- Webhook payloads are signed with HMAC-SHA256 for integrity verification

### Network Authentication

#### Password-Based Authentication

Claude Task Master implements password-based Bearer token authentication for network-accessible services:

**REST API (`claudetm-api`):**
- All endpoints except `/health`, `/healthz`, `/ready`, `/livez`, `/docs`, and `/openapi.json` require authentication
- Authentication enforced via `Authorization: Bearer <password>` header
- FastAPI middleware validates password before request processing
- Returns 401 (Unauthorized) for missing headers
- Returns 403 (Forbidden) for invalid passwords

**MCP Server (`claudetm-mcp`):**
- stdio transport: No authentication (local process communication)
- SSE and streamable-http transports: Require Bearer token authentication
- Starlette middleware validates Bearer tokens
- Local connections (localhost) are acceptable without auth
- Remote connections (non-localhost) require authentication

**Unified Server (`claudetm-server`):**
- Runs both REST API and MCP server with shared authentication
- Single password configuration applies to all services
- Supports both `CLAUDETM_PASSWORD` (plaintext) and `CLAUDETM_PASSWORD_HASH` (bcrypt)

#### Bcrypt Password Hashing

Passwords are secured using bcrypt, a deliberately slow cryptographic hash function designed to resist brute-force attacks:

**Algorithm Details:**
- Hashing function: bcrypt with 12 rounds
- Hash format: `$2b$12$...` (60 character string)
- Password limit: 72 bytes (UTF-8 encoded)
- Cost factor: 12 rounds (configurable in `src/claude_task_master/auth/password.py`)

**Verification Method:**
- bcrypt's `verify()` uses constant-time comparison by design
- Automatically resistant to timing attacks
- See `src/claude_task_master/auth/password.py` for implementation

**Password Generation:**
```bash
# Generate bcrypt hash (requires passlib[bcrypt])
python3 -c "from passlib.hash import bcrypt; print(bcrypt.hash('your-secure-password'))"
```

**Production Deployment:**
- Always use `CLAUDETM_PASSWORD_HASH` environment variable
- Never commit plaintext passwords to version control
- Store hashes in secrets management systems (AWS Secrets Manager, HashiCorp Vault, etc.)
- Use different passwords for dev/staging/production environments

#### Webhook Security

Webhooks use HMAC-SHA256 signatures to authenticate outgoing notifications:

**Signature Headers:**
- `X-Webhook-Signature`: Simple HMAC-SHA256(secret, payload)
- `X-Webhook-Signature-256`: Timestamped HMAC-SHA256(secret, timestamp + "." + payload) - **Recommended**
- `X-Webhook-Timestamp`: Unix timestamp for freshness validation
- `X-Webhook-Event`: Event type identifier
- `X-Webhook-Delivery-Id`: Unique delivery identifier

**Security Features:**
- All webhooks require a shared secret for signature generation
- Timestamped signatures prevent replay attacks (default 5-minute window)
- Constant-time comparison prevents timing attacks
- Raw request body is used for signature calculation (not parsed JSON)

**Signature Verification:**
- Webhook receivers MUST verify signatures using HMAC-SHA256
- Check timestamp freshness to prevent old replayed webhooks
- Use constant-time string/buffer comparison
- Verified examples provided for Python, Node.js, and TypeScript in `docs/authentication.md`

**Common Pitfalls:**
- ❌ Using parsed JSON instead of raw request body
- ❌ Using simple string comparison (vulnerable to timing attacks)
- ❌ Forgetting the timestamp in signature calculation
- ❌ Not validating timestamp freshness
- ✅ Always use raw bytes and constant-time comparison

## CI/CD Security

- GitHub Actions uses official, verified actions
- No custom shell scripts for sensitive operations
- Secrets are managed through GitHub Secrets
- CodeQL results are uploaded to GitHub's security infrastructure
- Docker images are built and published on release tags only
- Docker image scanning tools can be integrated for vulnerability detection

### Docker Image Security

Docker images published to GitHub Container Registry (ghcr.io):

**Build Security:**
- Multi-stage build reduces final image size and attack surface
- Base image: Official Python Alpine (lightweight)
- Non-root user execution (UID 1000)
- Minimal dependencies in final image
- `.dockerignore` excludes test files, git history, and development artifacts

**Runtime Security:**
- Images run as non-root user
- No hardcoded secrets in image layers
- Environment variables used for configuration
- Volume mounts for project and credentials directories
- Read-only volumes where applicable

**Image Distribution:**
- Signed image manifests (recommended)
- Version tags and `latest` tag for easy updates
- Automatic builds on release (v*.*.* tags)
- Built for multiple architectures (amd64, arm64)

**Volume Mounting Best Practices:**
- Mount `~/.claude` (credentials) as read-only when possible
- Mount project directory as bind mount
- Use named volumes for persistent state
- Ensure proper permissions on mounted directories

## Security Recommendations by Environment

### Development Environment

1. **Use plaintext passwords with `CLAUDETM_PASSWORD`**
   - ✅ Acceptable for local development only
   - ✅ Simplifies testing and debugging

2. **Use stdio MCP transport**
   - ✅ No network exposure
   - ✅ Most secure for development
   - ✅ Uses local Claude Desktop

3. **Network Security:**
   - Bind to `localhost` only
   - Restrict firewall access
   - Use VPN for remote development

### Staging Environment

1. **Use bcrypt-hashed passwords with `CLAUDETM_PASSWORD_HASH`**
   - ✅ Password never in plaintext
   - ✅ Closer to production practices

2. **Use SSE transport with authentication**
   - ✅ Network accessible
   - ✅ Password protected
   - ⚠️ Consider TLS with reverse proxy

3. **Network Security:**
   - Bind to internal network only
   - Use VPN for external access
   - Consider reverse proxy (nginx) for TLS

4. **Webhook Security:**
   - Use HTTPS endpoints only
   - Configure unique webhook secrets
   - Test signature verification in staging first

### Production Environment

1. **Use bcrypt-hashed passwords stored in secrets management**
   - ✅ AWS Secrets Manager, HashiCorp Vault, or cloud provider equivalent
   - ✅ Automatic secret rotation
   - ✅ Audit trail of access

2. **Use SSE transport with TLS**
   - ✅ Network accessible securely
   - ✅ Password protected
   - ✅ Encrypted in transit

3. **Network Security:**
   - Use reverse proxy (nginx, Caddy) for TLS termination
   - Bind MCP to internal network only
   - Implement rate limiting
   - Enable WAF (Web Application Firewall)
   - Restrict firewall to authorized IPs/VPCs

4. **Monitoring & Logging:**
   - Log all authentication attempts (both success and failure)
   - Alert on repeated failed authentication attempts
   - Implement centralized logging (CloudWatch, Datadog, ELK)
   - Retain logs for compliance (90+ days)

5. **Webhook Security:**
   - Use HTTPS endpoints with valid SSL certificates
   - Verify SSL certificates (`verify_ssl=True`)
   - Use unique webhook secrets per receiver
   - Rotate webhook secrets regularly
   - Monitor webhook delivery failures
   - Log webhook events for audit trail

6. **Docker Deployment:**
   - Use specific version tags (not `latest`)
   - Scan images for vulnerabilities before deployment
   - Run periodic security updates
   - Use container orchestration security features (Kubernetes NetworkPolicy, Pod Security Policy)

## Encryption and Transport Security

### In Transit

**HTTPS/TLS for REST API:**
- Use reverse proxy (nginx, Caddy) to terminate TLS
- Minimum TLS 1.2, recommend 1.3
- Use strong cipher suites
- Implement HSTS (HTTP Strict-Transport-Security) header

**WSS for MCP SSE:**
- Use secure WebSocket over TLS
- Requires reverse proxy configuration
- Match TLS configuration with REST API

**Webhook Delivery:**
- Always use HTTPS endpoints
- Verify SSL certificates
- Document expected certificate requirements

### At Rest

**Password Hashes:**
- Stored as bcrypt hashes (not plaintext)
- Never logged or exposed
- Optionally store in secrets management system

**OAuth Credentials:**
- Stored in `~/.claude/.credentials.json`
- File permissions: 600 (owner read/write only)
- Never committed to version control

**Webhook Secrets:**
- Stored as plaintext in configuration
- Should be stored in secrets management for production
- Use different secrets for different webhooks/environments

## Compliance

This project aims to follow:
- **OWASP Top 10** principles
  - A07:2021 – Identification and Authentication Failures: Implements Bearer token authentication and bcrypt hashing
  - A06:2021 – Vulnerable and Outdated Components: Regular dependency updates and security scanning
  - A01:2021 – Broken Access Control: Password authentication and Bearer token validation
- **Python Security Best Practices**
  - PEP 619: Code review practices
  - Type hints for catching potential issues
  - Regular dependency audits
- **GitHub Security Guidelines**
  - Secret scanning enabled
  - CodeQL analysis
  - Dependabot for automated updates
- **NIST Cybersecurity Framework** principles
  - Identify: Asset inventory and security scanning
  - Protect: Authentication, encryption, and access controls
  - Detect: Logging and monitoring
  - Respond: Incident response procedures
  - Recover: Backup and recovery procedures

## Security Contacts and Reporting

See [Reporting Security Issues](#reporting-security-issues) at the top of this document.

**Response SLA:** 48 hours for initial acknowledgment, 7 days for security patch release.
