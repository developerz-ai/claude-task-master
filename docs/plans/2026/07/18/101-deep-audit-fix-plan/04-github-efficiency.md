# 04 — GitHub client: N+1s, pagination, backoff, timeouts

> Part of [`overview.md`](overview.md). Depends on: none.

## Bad decisions
Every poll tick refetches static data (repo info, branch protection); GraphQL queries are single-page; no rate-limit awareness anywhere; `pr_context.py` bypasses the timeout-enforcing client.

## Files to change
- `github/client.py:149` (`_get_repo_info`) — called inside `get_pr_status` on EVERY 10s poll tick + 3 duplicate `gh repo view` sites in `pr_context.py:103,181,541`. Cache per client instance (~700+ calls saved per 2h CI wait).
- `workflow_stages.py:348` — refetches branch protection every tick; fetch once per wait (as `ci_helpers.py:80` already does).
- `github/client_pr.py:244` + `core/pr_context.py:190` — **P1**: `gh api --paginate` output parsed with single `json.loads` — multi-page = concatenated arrays `[...][...]` → JSONDecodeError; in `save_pr_comments` swallowed to 0 comments AFTER dirs were cleared (pr_context.py:167-177) → busiest PRs report "no actionable comments". Fix: `--slurp` + flatten, or `--jq '.[]'` JSON-lines. Also: don't clear dirs until the fetch succeeded.
- `github/client_pr.py:339,359` + `pr_context.py:262,553` — **P1**: GraphQL `contexts(first:50)`, `reviewThreads(first:100)`, `comments(first:100)` — no pagination: failing check #51 invisible; >100 threads undercounts `unresolved_threads` → merges over live feedback. Paginate via `pageInfo{hasNextPage endCursor}` or refuse to conclude "0 unresolved" when `hasNextPage`.
- `github/client.py:97-103` + `workflow_stages.py:480-493` + `ci_helpers.py:131` — **P1**: no 403/429 handling; error-retry loops at fixed 10s sustain rate-limit abuse (~2100 calls per CI wait). Detect rate-limit in stderr, honor Retry-After, exponential backoff + jitter.
- `core/pr_context.py:103,181,190,279,442,475,541,565` — **P1**: eight `subprocess.run(["gh",...])` with no `timeout=` → orchestrator hangs indefinitely holding the session lock. Route through `GitHubClient._run_gh_command` (30s default; also kills the duplicate repo-view fetches). Add `timeout=` to git calls at `fix_pr.py:31,42`, `workflow_stages.py:63,85,91`.
- `core/pr_context.py:76-88` — **P1**: CI run-id extracted from first URL in ALL check_details incl. green ones → downloads logs of the passing workflow, agent debugs blind. Filter to failing conclusions; collect the SET of distinct run ids, download each.
- `github/ci_logs.py:80` — jobs API without `--paginate` (default 30) → failed matrix job on page 2 missed. Add pagination.
- `github/client_ci.py:242-251` — `_find_failed_run_id` scans last 5 runs across ALL branches, falls back to `runs[0]` even if green. Pass `branch=`, drop fallback.
- `github/ci_logs.py:205-216` — `_is_error_line` matches `"0 failed"`, `"XFAIL"`. Anchor patterns (`\bFAILED\b`, `^##\[error\]`).
- `core/pr_context.py:399-529` — batching: 2 sequential GraphQL mutations PER thread in `post_comment_replies`/`resolve_addressed_threads`; use aliased mutations. Also `resolve_addressed_threads` force-resolves threads a human deliberately re-opened (`addressed_threads.json` never pruned) — only auto-resolve threads whose last comment is the bot's; drop from addressed set on new human comment.
- Design gap: PR *conversation* comments (`/issues/{n}/comments`) are never fetched — human "please also change X" feedback is invisible to the whole pipeline. Add to `save_pr_comments` (or extend the `get_pr_status` GraphQL — it already fetches threads; adding `databaseId` makes the comments pipeline zero extra calls).

## Tests
- `tests/github/`: paginated fixtures (2-page comments, 51 checks), rate-limit stderr → backoff, run-id selection with mixed green/red checks.

## Done when
- One repo-info fetch per client; one protection fetch per wait; paginated queries; every subprocess has a timeout.
