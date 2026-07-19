"""Tests for release phase prompts (prompts_release.py).

This module tests all public functions and constants from prompts_release.py:
- build_release_discovery_prompt: Discovery prompt generation
- build_release_check_prompt: Post-merge verification prompt
- extract_release_guide: Parser for discovery results
- parse_release_check_result: Parser for verification results
- extract_pr_release_checks: Per-PR release-checks extraction from plan.md

Key contracts verified:
- Round-trip planner-format fixtures for extract_pr_release_checks
- parse_release_check_result graceful degradation (no marker → skip, never pass)
- Prompt structure: correct markers, sections, and content
"""

from __future__ import annotations

import pytest

from claude_task_master.core.prompts_release import (
    RELEASE_CHECK_FAIL,
    RELEASE_CHECK_PASS,
    RELEASE_CHECK_SKIP,
    RELEASE_GUIDE_COMPLETE,
    build_release_check_prompt,
    build_release_discovery_prompt,
    extract_pr_release_checks,
    extract_release_guide,
    parse_release_check_result,
)

# =============================================================================
# Constants Tests
# =============================================================================


class TestReleaseConstants:
    """Tests for module-level marker constants."""

    def test_release_guide_complete_is_string(self) -> None:
        """RELEASE_GUIDE_COMPLETE is a non-empty string."""
        assert isinstance(RELEASE_GUIDE_COMPLETE, str)
        assert RELEASE_GUIDE_COMPLETE

    def test_release_check_pass_is_string(self) -> None:
        """RELEASE_CHECK_PASS is a non-empty string."""
        assert isinstance(RELEASE_CHECK_PASS, str)
        assert RELEASE_CHECK_PASS

    def test_release_check_fail_is_string(self) -> None:
        """RELEASE_CHECK_FAIL is a non-empty string."""
        assert isinstance(RELEASE_CHECK_FAIL, str)
        assert RELEASE_CHECK_FAIL

    def test_release_check_skip_is_string(self) -> None:
        """RELEASE_CHECK_SKIP is a non-empty string."""
        assert isinstance(RELEASE_CHECK_SKIP, str)
        assert RELEASE_CHECK_SKIP

    def test_constants_are_distinct(self) -> None:
        """All check marker constants are distinct from each other."""
        markers = {RELEASE_CHECK_PASS, RELEASE_CHECK_FAIL, RELEASE_CHECK_SKIP}
        assert len(markers) == 3

    def test_guide_complete_not_a_check_marker(self) -> None:
        """RELEASE_GUIDE_COMPLETE is distinct from check markers."""
        assert RELEASE_GUIDE_COMPLETE not in {
            RELEASE_CHECK_PASS,
            RELEASE_CHECK_FAIL,
            RELEASE_CHECK_SKIP,
        }


# =============================================================================
# build_release_discovery_prompt Tests
# =============================================================================


class TestBuildReleaseDiscoveryPromptBasic:
    """Tests for basic build_release_discovery_prompt behavior."""

    def test_returns_string(self) -> None:
        """Prompt is a non-empty string."""
        result = build_release_discovery_prompt()
        assert isinstance(result, str)
        assert result

    def test_release_guide_complete_marker_present(self) -> None:
        """Prompt instructs the agent to emit RELEASE_GUIDE_COMPLETE."""
        result = build_release_discovery_prompt()
        assert RELEASE_GUIDE_COMPLETE in result

    def test_no_file_write_instruction(self) -> None:
        """Prompt instructs agent NOT to write files."""
        result = build_release_discovery_prompt()
        assert "NOT write files" in result or "Do NOT write files" in result

    def test_output_as_text_instruction(self) -> None:
        """Prompt instructs agent to output guide as text."""
        result = build_release_discovery_prompt()
        assert "OUTPUT" in result or "output" in result

    def test_release_guide_header_in_output_example(self) -> None:
        """Prompt shows '# Release Guide' as the expected output header."""
        result = build_release_discovery_prompt()
        assert "# Release Guide" in result

    def test_probe_sections_present(self) -> None:
        """Prompt describes what to probe (deploy, health, DB, monitoring)."""
        result = build_release_discovery_prompt()
        assert "Deploy" in result or "deploy" in result
        assert "Health" in result or "health" in result
        assert "Database" in result or "database" in result or "DB" in result
        assert "Monitor" in result or "monitor" in result

    def test_accessible_surface_checklist_mentioned(self) -> None:
        """Prompt asks for an 'Accessible Surface' checklist."""
        result = build_release_discovery_prompt()
        assert "Accessible Surface" in result or "accessible" in result.lower()

    def test_reasonable_length(self) -> None:
        """Prompt has non-trivial length (instructs a multi-step probe)."""
        result = build_release_discovery_prompt()
        assert len(result) > 500

    def test_what_to_probe_section_present(self) -> None:
        """'What to Probe' section is included."""
        result = build_release_discovery_prompt()
        assert "What to Probe" in result or "Probe" in result


class TestBuildReleaseDiscoveryPromptOutputFormat:
    """Tests for output format instructions in the discovery prompt."""

    def test_output_format_section_present(self) -> None:
        """Prompt includes an 'Output Format' section."""
        result = build_release_discovery_prompt()
        assert "Output Format" in result or "Output" in result

    def test_skip_if_nothing_instruction(self) -> None:
        """Prompt tells agent what to output when nothing is found."""
        result = build_release_discovery_prompt()
        # Should describe the empty/nothing-to-verify case
        assert "nothing" in result.lower() or "NOTHING" in result

    def test_end_with_marker_instruction(self) -> None:
        """Prompt instructs agent to end with RELEASE_GUIDE_COMPLETE."""
        result = build_release_discovery_prompt()
        # The marker must appear twice: once in the 'nothing' template, once in
        # the output-format end-instruction (or at minimum once as instruction)
        assert result.count(RELEASE_GUIDE_COMPLETE) >= 1


# =============================================================================
# build_release_check_prompt Tests
# =============================================================================


SAMPLE_RELEASE_GUIDE = """# Release Guide

## Deploy
Code deploys via Vercel on push to main.

## Health Checks
- GET /api/health → 200

## Accessible Surface
- [x] GitHub Deployments API
- [x] Health endpoint at /api/health
- [ ] Direct DB access
"""


class TestBuildReleaseCheckPromptBasic:
    """Tests for basic build_release_check_prompt behavior."""

    def test_returns_string(self) -> None:
        """Prompt is a non-empty string."""
        result = build_release_check_prompt(release_guide=SAMPLE_RELEASE_GUIDE)
        assert isinstance(result, str)
        assert result

    def test_release_guide_included(self) -> None:
        """Release guide content appears in the prompt."""
        result = build_release_check_prompt(release_guide=SAMPLE_RELEASE_GUIDE)
        assert "Vercel" in result
        assert "/api/health" in result

    def test_release_check_markers_in_instructions(self) -> None:
        """Output instructions reference PASS, FAIL, and SKIP markers."""
        result = build_release_check_prompt(release_guide=SAMPLE_RELEASE_GUIDE)
        assert RELEASE_CHECK_PASS in result
        assert RELEASE_CHECK_FAIL in result
        assert RELEASE_CHECK_SKIP in result

    def test_release_verification_mode_mentioned(self) -> None:
        """Prompt identifies the RELEASE VERIFICATION mode."""
        result = build_release_check_prompt(release_guide=SAMPLE_RELEASE_GUIDE)
        assert "RELEASE VERIFICATION" in result

    def test_pr_number_default_placeholder(self) -> None:
        """Without pr_number, a placeholder is used (no crash)."""
        result = build_release_check_prompt(release_guide=SAMPLE_RELEASE_GUIDE)
        assert isinstance(result, str)

    def test_pr_number_included_when_provided(self) -> None:
        """PR number is included when provided."""
        result = build_release_check_prompt(
            release_guide=SAMPLE_RELEASE_GUIDE,
            pr_number=42,
        )
        assert "42" in result

    def test_pr_title_included_when_provided(self) -> None:
        """PR title is included when provided."""
        result = build_release_check_prompt(
            release_guide=SAMPLE_RELEASE_GUIDE,
            pr_title="Add user auth",
        )
        assert "Add user auth" in result

    def test_pr_number_and_title_combined(self) -> None:
        """Both PR number and title appear together."""
        result = build_release_check_prompt(
            release_guide=SAMPLE_RELEASE_GUIDE,
            pr_number=7,
            pr_title="Fix login bug",
        )
        assert "7" in result
        assert "Fix login bug" in result

    def test_reasonable_length(self) -> None:
        """Prompt has non-trivial length."""
        result = build_release_check_prompt(release_guide=SAMPLE_RELEASE_GUIDE)
        assert len(result) > 200


class TestBuildReleaseCheckPromptPrReleaseChecks:
    """Tests for the optional per-PR release checks section."""

    def test_no_pr_checks_by_default(self) -> None:
        """Without pr_release_checks, no PR-specific section is rendered."""
        result = build_release_check_prompt(
            release_guide=SAMPLE_RELEASE_GUIDE,
            pr_release_checks=None,
        )
        assert "PR-Specific" not in result

    def test_pr_release_checks_included_when_provided(self) -> None:
        """PR-specific checks are rendered when provided."""
        checks = "- Verify /api/v2/users returns 200\n- Check migration ran"
        result = build_release_check_prompt(
            release_guide=SAMPLE_RELEASE_GUIDE,
            pr_release_checks=checks,
        )
        assert "PR-Specific" in result
        assert "Verify /api/v2/users" in result
        assert "Check migration ran" in result

    def test_pr_checks_stripped(self) -> None:
        """Leading/trailing whitespace in pr_release_checks is stripped."""
        checks = "\n\n  - Deploy verified  \n\n"
        result = build_release_check_prompt(
            release_guide=SAMPLE_RELEASE_GUIDE,
            pr_release_checks=checks,
        )
        assert "Deploy verified" in result

    def test_empty_pr_release_checks_treated_as_none(self) -> None:
        """Empty string for pr_release_checks is effectively absent."""
        result = build_release_check_prompt(
            release_guide=SAMPLE_RELEASE_GUIDE,
            pr_release_checks="",
        )
        # Empty string is falsy — section must not appear
        assert "PR-Specific" not in result


class TestBuildReleaseCheckPromptVerificationSteps:
    """Tests for the verification steps section."""

    def test_verification_steps_present(self) -> None:
        """Prompt includes numbered verification steps."""
        result = build_release_check_prompt(release_guide=SAMPLE_RELEASE_GUIDE)
        assert "Verification" in result

    def test_deploy_status_step_present(self) -> None:
        """Deploy status check step is included."""
        result = build_release_check_prompt(release_guide=SAMPLE_RELEASE_GUIDE)
        assert "Deploy" in result or "deploy" in result

    def test_health_check_step_present(self) -> None:
        """Health check step is included."""
        result = build_release_check_prompt(release_guide=SAMPLE_RELEASE_GUIDE)
        assert "Health" in result or "health" in result

    def test_skip_if_nothing_instruction(self) -> None:
        """Prompt instructs to skip steps that cannot be done."""
        result = build_release_check_prompt(release_guide=SAMPLE_RELEASE_GUIDE)
        assert "skip" in result.lower() or "Skip" in result


# =============================================================================
# extract_release_guide Tests
# =============================================================================


class TestExtractReleaseGuideBasic:
    """Tests for extract_release_guide parser."""

    def test_strips_complete_marker(self) -> None:
        """RELEASE_GUIDE_COMPLETE marker is removed from output."""
        raw = f"# Release Guide\n\nContent here.\n\n{RELEASE_GUIDE_COMPLETE}"
        result = extract_release_guide(raw)
        assert RELEASE_GUIDE_COMPLETE not in result

    def test_preserves_guide_content(self) -> None:
        """Guide body content is preserved."""
        raw = f"# Release Guide\n\nDeploy via Vercel.\n\n{RELEASE_GUIDE_COMPLETE}"
        result = extract_release_guide(raw)
        assert "Deploy via Vercel" in result

    def test_starts_with_release_guide_header(self) -> None:
        """Result starts with '# Release Guide' header."""
        raw = f"# Release Guide\n\nContent.\n\n{RELEASE_GUIDE_COMPLETE}"
        result = extract_release_guide(raw)
        assert result.startswith("# Release Guide")

    def test_extracts_from_midpoint(self) -> None:
        """Extracts guide starting from '# Release Guide' if preceded by other text."""
        raw = (
            f"Thinking out loud...\nProcessing...\n# Release Guide\n\nReal content.\n\n"
            f"{RELEASE_GUIDE_COMPLETE}"
        )
        result = extract_release_guide(raw)
        assert result.startswith("# Release Guide")
        assert "Thinking out loud" not in result

    def test_case_insensitive_header(self) -> None:
        """Lowercase '# release guide' header is also accepted."""
        raw = f"# release guide\n\nContent here.\n\n{RELEASE_GUIDE_COMPLETE}"
        result = extract_release_guide(raw)
        assert "Content here" in result

    def test_fallback_wraps_unknown_content(self) -> None:
        """When no '# Release Guide' header is found, content is wrapped."""
        raw = f"Some random output.\n\n{RELEASE_GUIDE_COMPLETE}"
        result = extract_release_guide(raw)
        assert "# Release Guide" in result
        assert "Some random output" in result

    def test_marker_only_input(self) -> None:
        """Marker-only input still produces a release guide."""
        raw = RELEASE_GUIDE_COMPLETE
        result = extract_release_guide(raw)
        assert "# Release Guide" in result

    def test_no_marker_in_input(self) -> None:
        """Missing marker still works (marker removal is safe)."""
        raw = "# Release Guide\n\nContent without marker."
        result = extract_release_guide(raw)
        assert "Content without marker" in result

    def test_round_trip_content_preserved(self) -> None:
        """A complete guide round-trips: wrap in marker → extract → same body."""
        body = "# Release Guide\n\n## Deploy\nVercel auto-deploys on push."
        raw = f"{body}\n\n{RELEASE_GUIDE_COMPLETE}"
        extracted = extract_release_guide(raw)
        assert "Vercel auto-deploys on push" in extracted
        assert RELEASE_GUIDE_COMPLETE not in extracted


# =============================================================================
# parse_release_check_result Tests
# =============================================================================


class TestParseReleaseCheckResultPass:
    """Tests for PASS detection in parse_release_check_result."""

    def test_explicit_pass_marker_returns_pass(self) -> None:
        """Explicit RELEASE_CHECK: PASS marker returns status 'pass'."""
        result = parse_release_check_result(f"All good. {RELEASE_CHECK_PASS}")
        assert result["status"] == "pass"

    def test_pass_includes_details(self) -> None:
        """Details field contains the original result text."""
        raw = f"Health check OK. {RELEASE_CHECK_PASS}"
        result = parse_release_check_result(raw)
        assert result["details"] == raw

    def test_pass_marker_anywhere_in_text(self) -> None:
        """PASS marker detected regardless of position."""
        raw = f"{RELEASE_CHECK_PASS}\n\nAll checks verified."
        result = parse_release_check_result(raw)
        assert result["status"] == "pass"

    def test_pass_with_surrounding_context(self) -> None:
        """PASS with surrounding narrative text is correctly parsed."""
        raw = (
            "Checked GitHub Deployments — deployed.\n"
            "Hit /api/health — 200 OK.\n"
            f"{RELEASE_CHECK_PASS}"
        )
        result = parse_release_check_result(raw)
        assert result["status"] == "pass"


class TestParseReleaseCheckResultFail:
    """Tests for FAIL detection in parse_release_check_result."""

    def test_explicit_fail_marker_returns_fail(self) -> None:
        """Explicit RELEASE_CHECK: FAIL marker returns status 'fail'."""
        result = parse_release_check_result(f"Health check failed. {RELEASE_CHECK_FAIL}")
        assert result["status"] == "fail"

    def test_fail_includes_details(self) -> None:
        """Details field contains the original result text."""
        raw = f"Deploy timed out. {RELEASE_CHECK_FAIL}"
        result = parse_release_check_result(raw)
        assert result["details"] == raw

    def test_fail_marker_anywhere_in_text(self) -> None:
        """FAIL marker detected regardless of position."""
        raw = f"{RELEASE_CHECK_FAIL}\n\n/api/health returned 503."
        result = parse_release_check_result(raw)
        assert result["status"] == "fail"


class TestParseReleaseCheckResultSkip:
    """Tests for SKIP detection and graceful degradation."""

    def test_explicit_skip_marker_returns_skip(self) -> None:
        """Explicit RELEASE_CHECK: SKIP marker returns status 'skip'."""
        result = parse_release_check_result(f"No health endpoints found. {RELEASE_CHECK_SKIP}")
        assert result["status"] == "skip"

    def test_no_marker_defaults_to_skip(self) -> None:
        """No recognized marker → graceful degradation to 'skip' (never 'pass')."""
        result = parse_release_check_result("Deployment appears to be running.")
        assert result["status"] == "skip"

    def test_positive_sounding_without_marker_is_skip_not_pass(self) -> None:
        """Output sounding positive without explicit marker must not be scored PASS.

        This guards the same failure mode fixed in _parse_verification_result:
        'runs successfully but checks unmet' must never bubble up as pass.
        """
        result = parse_release_check_result(
            "The suite runs successfully but 2 release checks are unmet."
        )
        assert result["status"] == "skip"

    def test_generic_success_word_without_marker_is_skip(self) -> None:
        """A bare 'success' substring without the PASS marker is not PASS."""
        result = parse_release_check_result("Deployment was a success!")
        assert result["status"] == "skip"

    def test_empty_string_is_skip(self) -> None:
        """Empty output defaults to skip."""
        result = parse_release_check_result("")
        assert result["status"] == "skip"

    def test_empty_details_preserved(self) -> None:
        """Details field is the original (possibly empty) string."""
        result = parse_release_check_result("")
        assert result["details"] == ""


class TestParseReleaseCheckResultPriority:
    """Tests for marker precedence when multiple markers are present."""

    def test_pass_takes_priority_over_skip_when_pass_present(self) -> None:
        """When PASS marker is present alongside unrelated text, status is pass."""
        raw = f"Checked everything. {RELEASE_CHECK_PASS}\n\nNote: previous run was skipped."
        result = parse_release_check_result(raw)
        assert result["status"] == "pass"

    def test_fail_takes_priority_over_skip_text(self) -> None:
        """When FAIL marker is present, status is fail regardless of skip language."""
        raw = f"Will skip next time. {RELEASE_CHECK_FAIL}"
        result = parse_release_check_result(raw)
        assert result["status"] == "fail"

    def test_pass_before_fail_returns_pass(self) -> None:
        """If PASS marker appears before FAIL, the first check (PASS) wins."""
        # Implementation checks PASS first, so PASS wins
        raw = f"Mostly ok. {RELEASE_CHECK_PASS} But one thing failed. {RELEASE_CHECK_FAIL}"
        result = parse_release_check_result(raw)
        # PASS is checked first in the implementation → status is pass
        assert result["status"] == "pass"


class TestParseReleaseCheckResultStructure:
    """Tests for the return value structure."""

    def test_returns_dict(self) -> None:
        """Return value is a dict."""
        result = parse_release_check_result(RELEASE_CHECK_PASS)
        assert isinstance(result, dict)

    def test_dict_has_status_key(self) -> None:
        """Return value has 'status' key."""
        result = parse_release_check_result(RELEASE_CHECK_PASS)
        assert "status" in result

    def test_dict_has_details_key(self) -> None:
        """Return value has 'details' key."""
        result = parse_release_check_result(RELEASE_CHECK_PASS)
        assert "details" in result

    def test_status_is_one_of_three_values(self) -> None:
        """Status is always one of 'pass', 'fail', 'skip'."""
        for raw in [RELEASE_CHECK_PASS, RELEASE_CHECK_FAIL, RELEASE_CHECK_SKIP, "random text"]:
            result = parse_release_check_result(raw)
            assert result["status"] in {"pass", "fail", "skip"}


# =============================================================================
# extract_pr_release_checks Round-Trip Fixture Tests
# =============================================================================

# ---------------------------------------------------------------------------
# Representative plan fixtures: (plan_markdown, pr_number, expected_checks)
# ---------------------------------------------------------------------------

_PLAN_NO_RELEASE_CHECKS = """\
### PR 1: Schema

- [ ] `[coding]` Add user table
- [ ] `[coding]` Add index

### PR 2: API

- [ ] `[coding]` Add endpoint
"""

_PLAN_WITH_RELEASE_CHECKS_PR1 = """\
### PR 1: Schema

- [ ] `[coding]` Add user table

**Release checks:**
- Hit /api/health after deploy
- Run `prisma migrate status`

### PR 2: API

- [ ] `[coding]` Add endpoint
"""

_PLAN_WITH_RELEASE_CHECKS_PR2 = """\
### PR 1: Schema

- [ ] `[coding]` Add user table

### PR 2: API

- [ ] `[coding]` Add endpoint

**Release checks:**
- Verify /api/v2/users returns 200
- Check Sentry for new errors
"""

_PLAN_BOTH_PRS_HAVE_CHECKS = """\
### PR 1: Schema

- [ ] `[coding]` Add user table

**Release checks:**
- Check DB migration ran

### PR 2: API

- [ ] `[coding]` Add endpoint

**Release checks:**
- Hit /api/health
- Check deploy logs
"""

_PLAN_RELEASE_CHECKS_AT_EOF = """\
### PR 1: Schema

- [ ] `[coding]` Add migration

**Release checks:**
- Verify migration applied
- Check schema version"""

_PLAN_WITH_H3_PR_HEADERS = """\
## PR 1: Schema Changes

- [ ] Run migration

**Release checks:**
- Check migration status

## PR 2: API Changes

- [ ] Add endpoint
"""

_PLAN_LOWERCASE_RELEASE_CHECKS = """\
### PR 1: Schema

- [ ] Add table

**release checks:**
- verify deploy
- check logs
"""

# Parameterized fixtures: (plan, pr_number, should_find, expected_content_substring)
_ROUND_TRIP_CASES: list[tuple[str, str, int, bool, str | None]] = [
    (
        "no_release_checks_pr1",
        _PLAN_NO_RELEASE_CHECKS,
        1,
        False,
        None,
    ),
    (
        "no_release_checks_pr2",
        _PLAN_NO_RELEASE_CHECKS,
        2,
        False,
        None,
    ),
    (
        "has_checks_pr1",
        _PLAN_WITH_RELEASE_CHECKS_PR1,
        1,
        True,
        "Hit /api/health",
    ),
    (
        "has_checks_pr1_skips_pr2",
        _PLAN_WITH_RELEASE_CHECKS_PR1,
        2,
        False,
        None,
    ),
    (
        "has_checks_pr2",
        _PLAN_WITH_RELEASE_CHECKS_PR2,
        2,
        True,
        "Verify /api/v2/users",
    ),
    (
        "has_checks_pr2_skips_pr1",
        _PLAN_WITH_RELEASE_CHECKS_PR2,
        1,
        False,
        None,
    ),
    (
        "both_prs_pr1",
        _PLAN_BOTH_PRS_HAVE_CHECKS,
        1,
        True,
        "Check DB migration ran",
    ),
    (
        "both_prs_pr2",
        _PLAN_BOTH_PRS_HAVE_CHECKS,
        2,
        True,
        "Hit /api/health",
    ),
    (
        "checks_at_eof",
        _PLAN_RELEASE_CHECKS_AT_EOF,
        1,
        True,
        "Verify migration applied",
    ),
    (
        "h2_pr_headers_pr1",
        _PLAN_WITH_H3_PR_HEADERS,
        1,
        True,
        "Check migration status",
    ),
    (
        "h2_pr_headers_pr2",
        _PLAN_WITH_H3_PR_HEADERS,
        2,
        False,
        None,
    ),
    (
        "lowercase_header",
        _PLAN_LOWERCASE_RELEASE_CHECKS,
        1,
        True,
        "verify deploy",
    ),
]


class TestExtractPrReleaseChecksRoundTrip:
    """Round-trip tests for extract_pr_release_checks with planner-format fixtures.

    Each test case uses a representative plan in the format the planner emits
    and verifies that extract_pr_release_checks returns (or does not return)
    the expected checks for the given PR number.
    """

    @pytest.mark.parametrize(
        "plan,pr_number,should_find,expected_snippet",
        [
            (plan, pr_num, should_find, snippet)
            for _, plan, pr_num, should_find, snippet in _ROUND_TRIP_CASES
        ],
        ids=[name for name, *_ in _ROUND_TRIP_CASES],
    )
    def test_round_trip(
        self,
        plan: str,
        pr_number: int,
        should_find: bool,
        expected_snippet: str | None,
    ) -> None:
        """extract_pr_release_checks returns expected content or None per fixture."""
        result = extract_pr_release_checks(plan, pr_number)

        if should_find:
            assert result is not None, f"Expected checks for PR {pr_number} but got None"
            assert expected_snippet is not None
            assert expected_snippet in result, f"'{expected_snippet}' not in {result!r}"
        else:
            assert result is None, f"Expected None for PR {pr_number} but got {result!r}"


class TestExtractPrReleaseChecksIsolation:
    """Tests that extract_pr_release_checks isolates each PR's checks."""

    def test_does_not_bleed_pr1_checks_into_pr2(self) -> None:
        """Checks from PR 1 do not appear when requesting PR 2 checks."""
        checks = extract_pr_release_checks(_PLAN_BOTH_PRS_HAVE_CHECKS, pr_number=2)
        assert checks is not None
        assert "Check DB migration ran" not in checks

    def test_does_not_bleed_pr2_checks_into_pr1(self) -> None:
        """Checks from PR 2 do not appear when requesting PR 1 checks."""
        checks = extract_pr_release_checks(_PLAN_BOTH_PRS_HAVE_CHECKS, pr_number=1)
        assert checks is not None
        assert "Hit /api/health" not in checks  # PR 2's check
        assert "Check DB migration ran" in checks

    def test_nonexistent_pr_returns_none(self) -> None:
        """Requesting checks for a PR number not in the plan returns None."""
        result = extract_pr_release_checks(_PLAN_WITH_RELEASE_CHECKS_PR1, pr_number=99)
        assert result is None

    def test_empty_plan_returns_none(self) -> None:
        """Empty plan string returns None."""
        result = extract_pr_release_checks("", pr_number=1)
        assert result is None

    def test_plan_without_pr_headers_returns_none(self) -> None:
        """Plan with no PR headers returns None."""
        plan = "- [ ] Do this\n- [ ] Do that\n"
        result = extract_pr_release_checks(plan, pr_number=1)
        assert result is None


class TestExtractPrReleaseChecksContent:
    """Tests for content correctness in extracted checks."""

    def test_multiline_checks_all_extracted(self) -> None:
        """All check lines are extracted, not just the first."""
        checks = extract_pr_release_checks(_PLAN_BOTH_PRS_HAVE_CHECKS, pr_number=2)
        assert checks is not None
        assert "Hit /api/health" in checks
        assert "Check deploy logs" in checks

    def test_eof_checks_all_extracted(self) -> None:
        """Checks at end of file (no trailing blank line) are fully captured."""
        checks = extract_pr_release_checks(_PLAN_RELEASE_CHECKS_AT_EOF, pr_number=1)
        assert checks is not None
        assert "Verify migration applied" in checks
        assert "Check schema version" in checks

    def test_task_checkboxes_not_included(self) -> None:
        """Regular task checkbox lines are not included in release checks."""
        checks = extract_pr_release_checks(_PLAN_WITH_RELEASE_CHECKS_PR1, pr_number=1)
        assert checks is not None
        # The coding task line must NOT appear in the checks
        assert "[coding]" not in checks
        assert "Add user table" not in checks

    def test_result_is_stripped_string(self) -> None:
        """Returned checks string has no leading/trailing blank lines."""
        checks = extract_pr_release_checks(_PLAN_WITH_RELEASE_CHECKS_PR1, pr_number=1)
        assert checks is not None
        assert checks == checks.strip()


# =============================================================================
# Integration Tests: prompt round-trips via markers
# =============================================================================


class TestPromptRoundTrips:
    """Integration tests that exercise the full prompt→marker→parse cycle."""

    def test_discovery_prompt_contains_guide_complete_marker_once(self) -> None:
        """The discovery prompt embeds RELEASE_GUIDE_COMPLETE at least once."""
        prompt = build_release_discovery_prompt()
        assert RELEASE_GUIDE_COMPLETE in prompt

    def test_check_prompt_embeds_all_three_check_markers(self) -> None:
        """The check prompt embeds PASS, FAIL, and SKIP markers for instructions."""
        prompt = build_release_check_prompt(release_guide=SAMPLE_RELEASE_GUIDE)
        assert RELEASE_CHECK_PASS in prompt
        assert RELEASE_CHECK_FAIL in prompt
        assert RELEASE_CHECK_SKIP in prompt

    def test_discovery_guide_complete_survived_extraction(self) -> None:
        """Marker inserted by discovery prompt is consumed by extract_release_guide."""
        # Simulate what the release discovery agent outputs
        simulated_agent_output = (
            f"# Release Guide\n\n## Deploy\nDeploys via Vercel.\n\n{RELEASE_GUIDE_COMPLETE}"
        )
        extracted = extract_release_guide(simulated_agent_output)
        assert RELEASE_GUIDE_COMPLETE not in extracted
        assert "Deploys via Vercel" in extracted

    def test_check_pass_round_trip(self) -> None:
        """Simulated PASS agent output parses as status=pass."""
        # The agent uses the marker from the check prompt instructions
        simulated = f"Health check OK. /api/health → 200.\n{RELEASE_CHECK_PASS}"
        parsed = parse_release_check_result(simulated)
        assert parsed["status"] == "pass"

    def test_check_fail_round_trip(self) -> None:
        """Simulated FAIL agent output parses as status=fail."""
        simulated = f"Deploy timed out after 5 min.\n{RELEASE_CHECK_FAIL}"
        parsed = parse_release_check_result(simulated)
        assert parsed["status"] == "fail"

    def test_check_skip_round_trip(self) -> None:
        """Simulated SKIP agent output parses as status=skip."""
        simulated = f"No health endpoints available.\n{RELEASE_CHECK_SKIP}"
        parsed = parse_release_check_result(simulated)
        assert parsed["status"] == "skip"

    def test_check_prompt_with_pr_checks_includes_checks_in_output(self) -> None:
        """Per-PR checks injected into the check prompt appear in the prompt body."""
        pr_checks = "- Verify /api/v2/users returns 200\n- Check Sentry error rate"
        prompt = build_release_check_prompt(
            release_guide=SAMPLE_RELEASE_GUIDE,
            pr_number=3,
            pr_title="Add v2 users API",
            pr_release_checks=pr_checks,
        )
        assert "Verify /api/v2/users" in prompt
        assert "Check Sentry error rate" in prompt
        assert "3" in prompt
        assert "Add v2 users API" in prompt


class TestContextPersistsAcrossSessions:
    """Tests verifying that the release guide persists across simulated sessions.

    The release guide is generated once (session 1) and reused in subsequent
    sessions (session 2+). These tests verify that build_release_check_prompt
    faithfully embeds the persisted guide so the agent has full context each
    time — even when the prompt is rebuilt from scratch in a later session.
    """

    def test_same_guide_produces_identical_check_prompts(self) -> None:
        """Two calls with the same release guide produce identical prompts."""
        prompt1 = build_release_check_prompt(
            release_guide=SAMPLE_RELEASE_GUIDE,
            pr_number=1,
            pr_title="Schema",
        )
        prompt2 = build_release_check_prompt(
            release_guide=SAMPLE_RELEASE_GUIDE,
            pr_number=1,
            pr_title="Schema",
        )
        assert prompt1 == prompt2

    def test_guide_content_present_in_second_session_prompt(self) -> None:
        """Release guide content from session 1 is fully present in session 2 prompt.

        Simulates: session 1 generates release.md, session 2 loads it from disk
        and passes it to build_release_check_prompt for a different PR.
        """
        # Session 1: discovery agent produces a guide
        guide_session1 = extract_release_guide(
            "# Release Guide\n\n## Deploy\nVercel auto-deploys on push to main.\n\n"
            "## Health Checks\n- /api/health → 200\n\n"
            f"{RELEASE_GUIDE_COMPLETE}"
        )

        # Session 2: the saved guide is reloaded and injected for a new PR
        prompt_session2 = build_release_check_prompt(
            release_guide=guide_session1,
            pr_number=2,
            pr_title="Add API v2",
        )

        # Full guide content must be present
        assert "Vercel auto-deploys on push to main" in prompt_session2
        assert "/api/health" in prompt_session2

    def test_pr_specific_checks_vary_per_pr_but_guide_stays_same(self) -> None:
        """The shared guide is constant; only per-PR checks differ between sessions."""
        guide = extract_release_guide(
            f"# Release Guide\n\nDeploy via Vercel.\n\n{RELEASE_GUIDE_COMPLETE}"
        )

        prompt_pr1 = build_release_check_prompt(
            release_guide=guide,
            pr_number=1,
            pr_release_checks="- Check DB migration",
        )
        prompt_pr2 = build_release_check_prompt(
            release_guide=guide,
            pr_number=2,
            pr_release_checks="- Verify /api/health",
        )

        # Guide is identical in both
        assert "Deploy via Vercel" in prompt_pr1
        assert "Deploy via Vercel" in prompt_pr2

        # Per-PR checks differ
        assert "Check DB migration" in prompt_pr1
        assert "Check DB migration" not in prompt_pr2
        assert "Verify /api/health" in prompt_pr2
        assert "Verify /api/health" not in prompt_pr1
