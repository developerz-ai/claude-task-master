"""Release Phase Prompts for Claude Task Master.

This module contains prompts for the release phase:
1. Project-level release discovery — generates release.md by probing
   deploy configs, monitoring, DB access, health endpoints, env vars.
2. Per-PR release verification — runs after merge to verify deployment.

release.md is generated once during planning (like coding-style.md) and
injected into planning prompts so the planner can add per-PR release checks.

The release phase is optional by nature: if discovery finds nothing to
verify (no deploy config, no health endpoints, no monitoring), the
releasing stage becomes a no-op pass-through.
"""

from __future__ import annotations

from .prompts_base import PromptBuilder

# Completion markers
RELEASE_GUIDE_COMPLETE = "RELEASE_GUIDE_COMPLETE"
RELEASE_CHECK_PASS = "RELEASE_CHECK: PASS"
RELEASE_CHECK_FAIL = "RELEASE_CHECK: FAIL"
RELEASE_CHECK_SKIP = "RELEASE_CHECK: SKIP"


def build_release_discovery_prompt() -> str:
    """Build the prompt for discovering project release capabilities.

    The agent probes the codebase and environment to map what release
    verification is possible. It checks deploy configs, monitoring,
    DB access, health endpoints, env vars, CI/CD pipelines.

    Returns:
        Complete release discovery prompt.
    """
    builder = PromptBuilder(
        intro=f"""Analyze this project's deployment and release infrastructure. Create a concise release guide (under 500 words).
This gets injected into planning so the planner knows what post-merge checks are possible.

All tools available. Probe everything — files, env vars, configs, CLIs. Do NOT write files — OUTPUT guide as text.

If you find NOTHING to verify (no deploy config, no URLs, no monitoring), output:
```
# Release Guide

No release verification available for this project.
Reason: [why — no deploy config found, local-only project, etc.]

{RELEASE_GUIDE_COMPLETE}
```"""
    )

    builder.add_section(
        "What to Probe",
        """**1. Deploy Pipeline** — How does code reach production?
- Check: `vercel.json`, `netlify.toml`, `fly.toml`, `render.yaml`, `railway.json`, `Dockerfile`, `docker-compose.yml`
- Check: `.github/workflows/*.yml` for deploy jobs, `Procfile`, `app.yaml` (GCP), `serverless.yml`
- Check: `package.json` scripts for deploy commands
- Run: `vercel --version`, `fly version`, `railway --version`, `heroku --version` (check what CLIs exist)

**2. Health & Smoke Endpoints** — What can we hit after deploy?
- Grep for: `/health`, `/api/health`, `/healthz`, `/readyz`, `/status`, `healthCheck`
- Check route files for any status/health endpoints
- Look for base URL in configs, env vars, `NEXT_PUBLIC_`, `VITE_`

**3. Database** — What migration framework? Do we have access?
- Check: `prisma/`, `drizzle/`, `db/migrate/` (Rails), `alembic/`, `migrations/`, `knex`
- Migration commands: `prisma migrate status`, `rails db:migrate:status`, `alembic current`
- Check `.env`, `.env.production`, `.env.local` for DATABASE_URL (note: DON'T output secrets, just note if they exist)

**4. Monitoring & Error Tracking** — Can we check for new errors?
- Check: Sentry config (`sentry.*.config.*`, `@sentry/`, `sentry_sdk`), Bugsnag, Datadog
- Check env for: `SENTRY_DSN`, `SENTRY_AUTH_TOKEN`, `BUGSNAG_API_KEY`, `DD_API_KEY`
- If Sentry configured + auth token exists, we can query error rates post-deploy

**5. Environment Variables** — What production access exists?
- Check `.env`, `.env.production`, `.env.local`, `.env.example`
- Look for: API keys, deploy tokens, cloud credentials
- DON'T output secret values — just note which vars are set vs missing

**6. Cloud Access** — What CLIs/credentials are available?
- Run: `gcloud auth list`, `aws sts get-caller-identity`, `az account show` (check what works)
- Check for cloud config dirs: `~/.aws/`, `~/.config/gcloud/`, `~/.azure/`""",
    )

    builder.add_section(
        "Output Format",
        f"""Output markdown starting with `# Release Guide`. Sections (skip if N/A):

- **Deploy** — How code deploys, what triggers it, how to check status
- **Health Checks** — Endpoints to hit after deploy, expected responses
- **Database** — Migration framework, commands, access level
- **Monitoring** — Error tracking service, how to check for new errors
- **Environment** — What production env vars are set (not values, just which exist)
- **Accessible Surface** — Checklist of what we CAN vs CANNOT verify:
  ```
  - [x] GitHub Deployments API
  - [x] Health endpoint at /api/health
  - [ ] Direct DB access (migrations only)
  - [ ] Sentry API (no SENTRY_AUTH_TOKEN)
  ```

End with: `{RELEASE_GUIDE_COMPLETE}`""",
    )

    return builder.build()


def build_release_check_prompt(
    release_guide: str,
    pr_release_checks: str | None = None,
    pr_number: int | None = None,
    pr_title: str | None = None,
) -> str:
    """Build the prompt for post-merge release verification.

    This runs after a PR is merged. The agent verifies the deployment
    using whatever access is available (health checks, deploy status,
    error monitoring, migration status).

    Args:
        release_guide: Project-level release.md content.
        pr_release_checks: Per-PR release checks from plan.md (if any).
        pr_number: The PR number that was just merged.
        pr_title: The PR title for context.

    Returns:
        Complete release verification prompt.
    """
    builder = PromptBuilder(
        intro=f"""You are Claude Task Master in RELEASE VERIFICATION mode.

PR #{pr_number or "?"} ({pr_title or "unknown"}) was just merged.
Verify the deployment is healthy. Use all available tools.

**Rules:**
- Only check what you actually have access to (see release guide below)
- If you can't reach something, skip it — don't fail
- Be fast — this runs between every PR merge
- If there's NOTHING to check, immediately output `{RELEASE_CHECK_SKIP}`"""
    )

    builder.add_section(
        "Project Release Guide",
        release_guide.strip(),
    )

    if pr_release_checks:
        builder.add_section(
            "PR-Specific Release Checks",
            f"""These checks were planned specifically for this PR:

{pr_release_checks.strip()}

Run each check that you have access to. Skip checks you can't perform.""",
        )

    builder.add_section(
        "Verification Steps",
        """Run checks in this order (skip any you can't do):

1. **Deploy status** — Check GitHub Deployments API: `gh api repos/:owner/:repo/deployments --jq '.[0]'`
2. **Wait for deploy** — If deploy is pending, poll until complete (max 5 min, 30s intervals)
3. **Health check** — Hit health endpoints, verify 200 response
4. **DB migrations** — Check migration status if applicable
5. **Error monitoring** — Check Sentry/Bugsnag for new errors since merge (if API access)
6. **Smoke test** — Hit key endpoints changed by this PR (if URLs available)""",
    )

    builder.add_section(
        "Output",
        f"""Report what you checked and results. Keep it terse.

If ALL checks pass (or nothing to check): `{RELEASE_CHECK_PASS}`
If any check fails: `{RELEASE_CHECK_FAIL}` + what failed + suggested fix
If nothing was checkable: `{RELEASE_CHECK_SKIP}`""",
    )

    return builder.build()


def extract_release_guide(result: str) -> str:
    """Extract the release guide from the discovery result.

    Args:
        result: The raw output from the release discovery agent.

    Returns:
        The extracted release guide content.
    """
    content = result.replace(RELEASE_GUIDE_COMPLETE, "").strip()

    if content.startswith("# Release Guide") or content.startswith("# release guide"):
        return content

    if "# Release Guide" in content:
        idx = content.index("# Release Guide")
        return content[idx:].strip()

    return f"# Release Guide\n\n{content}"


def parse_release_check_result(result: str) -> dict[str, str]:
    """Parse the result of a release verification check.

    Args:
        result: The raw output from the release check agent.

    Returns:
        Dict with 'status' (pass/fail/skip) and 'details'.
    """
    if RELEASE_CHECK_PASS in result:
        return {"status": "pass", "details": result}
    elif RELEASE_CHECK_FAIL in result:
        return {"status": "fail", "details": result}
    elif RELEASE_CHECK_SKIP in result:
        return {"status": "skip", "details": result}
    else:
        # Default to skip if no marker found (graceful degradation)
        return {"status": "skip", "details": result}


def extract_pr_release_checks(plan: str, pr_number: int) -> str | None:
    """Extract per-PR release checks from plan.md.

    Looks for a **Release checks:** section under the PR header.

    Args:
        plan: The full plan.md content.
        pr_number: The PR group number (1-indexed).

    Returns:
        The release checks text for this PR, or None if not found.
    """
    import re

    lines = plan.split("\n")
    in_target_pr = False
    in_release_checks = False
    release_lines: list[str] = []

    for line in lines:
        # Check for PR header
        pr_match = re.match(r"^#{2,3}\s+PR\s*(\d+)", line, re.IGNORECASE)
        if pr_match:
            if int(pr_match.group(1)) == pr_number:
                in_target_pr = True
                in_release_checks = False
                release_lines = []
            elif in_target_pr:
                # Hit next PR header, stop
                break
            continue

        if not in_target_pr:
            continue

        # Look for release checks section
        if re.match(r"^\*\*Release checks:?\*\*", line.strip(), re.IGNORECASE):
            in_release_checks = True
            continue

        # If in release checks, collect lines until empty line or new section
        if in_release_checks:
            stripped = line.strip()
            if stripped.startswith("### ") or stripped.startswith("## "):
                break  # New section header
            if stripped:
                release_lines.append(stripped)
            elif release_lines:
                # Empty line after content = end of section
                break

    return "\n".join(release_lines) if release_lines else None
