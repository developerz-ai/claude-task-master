# Advanced Workflows

Complex multi-step scenarios and advanced usage patterns for Claude Task Master.

## Example 1: Multi-Part Feature Development

### Scenario
Large feature that should be broken into multiple PRs.

### Approach
```bash
# Part 1: Data model
claudetm start "Add Comment model with user relationship, timestamps, and soft delete"
# Wait for completion and merge

# Part 2: API endpoints
claudetm start "Add CRUD endpoints for comments - GET, POST, PUT, DELETE with proper auth"
# Wait for completion and merge

# Part 3: Frontend integration
claudetm start "Add comment UI component with real-time updates using the comment API"
```

### Benefits
- Smaller, reviewable PRs
- Incremental progress
- Easy to revert if needed
- Clear git history

## Example 2: Dependency Chain

### Scenario
Task B depends on Task A being merged.

### Workflow
```bash
# Start Task A
claudetm start "Add email service with SendGrid integration" --no-auto-merge

# Review and merge manually when satisfied
gh pr view
gh pr merge --squash

# Now start dependent Task B
claudetm start "Add password reset using email service"
```

## Example 3: Experimental Feature Branch

### Scenario
Try out a new approach without committing to main branch.

### Workflow
```bash
# Create experimental branch
git checkout -b experiment/new-approach

# Try the new approach
claudetm start "Refactor to use event-driven architecture" --max-sessions 10 --no-auto-merge

# Review results
git diff main

# If good, merge to main
git checkout main
git merge experiment/new-approach
gh pr create

# If not good, abandon
git checkout main
git branch -D experiment/new-approach
```

## Example 4: Iterative Refinement

### Scenario
Feature works but needs polish.

### Workflow
```bash
# Initial implementation
claudetm start "Add search functionality"
# -> Creates PR, merges

# Refinement 1: Performance
claudetm start "Optimize search - add indexing and caching"
# -> Creates PR, merges

# Refinement 2: UX
claudetm start "Improve search UX - add autocomplete and search history"
# -> Creates PR, merges

# Refinement 3: Testing
claudetm start "Add comprehensive tests for search including edge cases"
# -> Creates PR, merges
```

## Example 5: Emergency Hotfix

### Scenario
Production bug needs immediate fix.

### Workflow
```bash
# Create hotfix branch from production
git checkout -b hotfix/critical-bug production

# Fix with high urgency
claudetm start "URGENT: Fix null pointer in payment processing" \
  --model opus \
  --no-auto-merge \
  --max-sessions 3

# Review immediately
gh pr view
gh pr diff

# Test locally
pytest tests/test_payment.py

# Merge to production
gh pr merge --squash

# Backport to main
git checkout main
git cherry-pick <commit-hash>
git push
```

## Example 6: Parallel Development

### Scenario
Multiple independent features can be developed simultaneously.

### Approach
```bash
# Terminal 1: Feature A
git checkout -b feature/user-profiles
claudetm start "Add user profile customization"

# Terminal 2: Feature B (different branch)
git checkout -b feature/notifications
claudetm start "Add in-app notification system"

# Terminal 3: Feature C (different branch)
git checkout -b feature/export
claudetm start "Add data export to CSV and JSON"
```

### Coordination
- Each runs in separate branch
- PRs can be reviewed independently
- Merge order based on readiness
- Resolve conflicts if any

## Example 7: Migration Project

### Scenario
Migrate from old framework to new one incrementally.

### Phased Approach
```bash
# Phase 1: Setup
claudetm start "Set up new framework alongside old one with routing to direct traffic"

# Phase 2: Migrate users module
claudetm start "Migrate user management from old framework to new - maintain API compatibility"

# Phase 3: Migrate orders
claudetm start "Migrate order processing to new framework"

# Phase 4: Migrate products
claudetm start "Migrate product catalog to new framework"

# Phase 5: Remove old framework
claudetm start "Remove old framework code and dependencies after all modules migrated"
```

## Example 8: Performance Optimization Campaign

### Workflow
```bash
# 1. Baseline measurement
claudetm start "Add performance monitoring and establish baseline metrics"

# 2. Database optimization
claudetm start "Optimize database queries - add indexes, fix N+1 queries, add query caching"

# 3. API optimization
claudetm start "Optimize API response times - add Redis caching, compress responses, use ETags"

# 4. Frontend optimization
claudetm start "Optimize frontend - lazy load components, optimize bundle size, add service worker"

# 5. Verify improvements
claudetm start "Add performance tests and document improvements in PERFORMANCE.md"
```

## Example 9: Security Audit Remediation

### Scenario
Security audit found multiple issues.

### Systematic Approach
```bash
# Critical severity first
claudetm start "Fix SQL injection in search endpoint (CRITICAL)" --no-auto-merge --model opus

# High severity
claudetm start "Fix XSS vulnerability in comment rendering (HIGH)" --no-auto-merge --model opus

# Medium severity
claudetm start "Add rate limiting to prevent brute force attacks (MEDIUM)"

# Low severity
claudetm start "Update dependencies with known vulnerabilities (LOW)"

# Add security measures
claudetm start "Add security headers and implement CSP (PREVENTIVE)"
```

## Example 10: Legacy Code Modernization

### Gradual Refactoring
```bash
# Week 1: Add tests to legacy code
claudetm start "Add comprehensive tests for legacy auth module to enable safe refactoring"

# Week 2: Add type hints
claudetm start "Add type hints to auth module"

# Week 3: Extract functions
claudetm start "Refactor auth module - extract validation and encryption to separate functions"

# Week 4: Update to modern patterns
claudetm start "Update auth to use async/await and dataclasses"

# Week 5: Documentation
claudetm start "Document refactored auth module and create migration guide"
```

## Example 11: API Versioning

### Implementing v2 API
```bash
# Step 1: Create v2 structure
claudetm start "Create API v2 structure with separate routing and controllers"

# Step 2: Migrate endpoints gradually
claudetm start "Migrate user endpoints to API v2 with improved schema"
claudetm start "Migrate order endpoints to API v2"
claudetm start "Migrate product endpoints to API v2"

# Step 3: Deprecate v1
claudetm start "Add deprecation warnings to API v1 endpoints"

# Step 4: Eventually remove v1
claudetm start "Remove API v1 after deprecation period and migration complete"
```

## Example 12: Compliance Implementation

### GDPR Compliance Project
```bash
# User rights
claudetm start "Implement GDPR data export - user can download all their data in JSON format"
claudetm start "Implement GDPR right to erasure - user can delete their account and all data"

# Consent management
claudetm start "Add cookie consent banner and preference management"
claudetm start "Add email marketing consent with double opt-in"

# Data protection
claudetm start "Add data encryption at rest for sensitive user fields"
claudetm start "Implement data retention policies and automated cleanup"

# Documentation
claudetm start "Create privacy policy and data processing documentation"
```

## Advanced Techniques

### 1. State Inspection Mid-Task

```bash
# Start task
claudetm start "Complex refactoring"

# In another terminal, monitor progress
watch -n 5 'claudetm status && claudetm plan'

# Check what's happening
claudetm logs -n 50

# View accumulated context
claudetm context
```

### 2. Strategic Pausing

```bash
# Pause after each major milestone
claudetm start "Large feature" --pause-on-pr

# After first PR
claudetm resume  # Creates next PR
# Repeat for each phase
```

### 3. Session Limits for Exploration

```bash
# Limit sessions for experimental work
claudetm start "Try implementing feature X" --max-sessions 5

# If it works well, continue
claudetm resume  # Remove session limit

# If not, clean and try different approach
claudetm clean -f
claudetm start "Try implementing feature X differently" --max-sessions 5
```

### 4. Model Selection Strategy

```bash
# Simple, clear tasks
claudetm start "Fix typo in README" --model haiku

# Standard features
claudetm start "Add pagination to API" --model sonnet

# Complex architecture decisions
claudetm start "Design and implement microservice architecture" --model opus
```

### 5. Checkpointing for Safety

```bash
# Enable checkpointing for risky changes
claudetm start "Major database schema refactor" --checkpointing

# If something goes wrong, checkpoint allows rollback
```

## Handling Edge Cases

### CI Failures During Multi-Step Process

```bash
# If CI fails, Claude handles it automatically
# But you can monitor and intervene if needed

# Check CI status
claudetm ci-status

# View failure details
claudetm ci-logs

# Claude will fix and retry
# If stuck, you can:
# 1. Let it continue (resume)
# 2. Investigate and fix manually
# 3. Abandon and restart
```

### Merge Conflicts

```bash
# Claude attempts to handle conflicts
# If too complex, it will pause

# You can:
# 1. Resolve manually
git pull origin main
git merge --no-ff origin/main
# Fix conflicts
git commit

# 2. Resume Claude to continue
claudetm resume
```

### Resource Constraints

```bash
# Limit sessions to prevent runaway costs
claudetm start "Complex task" --max-sessions 20

# Use cheaper model for parts of the work
claudetm start "Add tests" --model sonnet  # After opus did implementation
```

## Production Readiness Checklist

Use claudetm to complete each item:

```bash
# Code Quality
claudetm start "Add type hints to all Python files"
claudetm start "Increase test coverage to 90%+"
claudetm start "Fix all linting issues and add pre-commit hooks"

# Documentation
claudetm start "Add comprehensive README with setup and usage"
claudetm start "Generate API documentation"
claudetm start "Create deployment guide"

# Security
claudetm start "Run security audit and fix all findings"
claudetm start "Add input validation and sanitization"
claudetm start "Implement rate limiting and CORS"

# Performance
claudetm start "Add performance monitoring and logging"
claudetm start "Optimize database queries and add caching"
claudetm start "Set up CDN for static assets"

# DevOps
claudetm start "Create Docker containerization"
claudetm start "Set up CI/CD pipeline"
claudetm start "Add health check endpoints"

# Monitoring
claudetm start "Integrate error tracking (Sentry/Rollbar)"
claudetm start "Add application metrics and dashboards"
claudetm start "Set up alerting for critical errors"
```

## Anti-Patterns to Avoid

### ❌ Don't: Vague Goals
```bash
# Bad
claudetm start "Make the app better"

# Good
claudetm start "Reduce API response time by optimizing database queries and adding caching"
```

### ❌ Don't: Too Much at Once
```bash
# Bad
claudetm start "Rewrite entire application in new framework, add tests, update docs, and deploy"

# Good
claudetm start "Set up new framework alongside old one"
# Then tackle each migration piece separately
```

### ❌ Don't: Ignore CI Feedback
```bash
# Bad: Force merge even if CI fails

# Good: Let Claude fix CI issues or investigate manually
claudetm ci-logs
```

### ❌ Don't: Skip Reviews
```bash
# Bad: Always use --auto-merge without reviewing

# Good: Review important changes
claudetm start "Critical security fix" --no-auto-merge
gh pr view
gh pr diff
```

## Best Practices Summary

1. **Break Down Large Tasks**: Multiple smaller PRs > one giant PR
2. **Use Branches**: Experiment safely in feature branches
3. **Monitor Progress**: Check status and logs regularly
4. **Set Limits**: Use --max-sessions for complex/uncertain tasks
5. **Choose Right Model**: Match model to task complexity
6. **Review Output**: Always review what gets merged
7. **Document Learnings**: Check `claudetm context` for insights
8. **Handle Failures Gracefully**: Let Claude retry, intervene when needed
9. **Test Thoroughly**: Don't skip testing steps
10. **Version Control Everything**: Commit often, push regularly

## Next Steps

You've completed all the examples! Now you're ready to:

- Apply these patterns to your own projects
- Experiment with different workflows
- Optimize your development process
- Build production-ready applications with Claude Task Master

For more information:
- [README](../README.md) - Main documentation
- [CONTRIBUTING](../CONTRIBUTING.md) - Contribute to the project
- [GitHub Issues](https://github.com/developerz-ai/claude-task-master/issues) - Report bugs or request features
