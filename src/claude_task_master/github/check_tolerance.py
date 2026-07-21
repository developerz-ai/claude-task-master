"""Tolerated (non-blocking) CI check failures.

Some status checks report ``FAILURE`` for reasons that have nothing to do with
the code under review and that no commit can fix. Treating those as CI failures
sends the orchestrator into a pointless fix session and then loops on the same
red check forever.

The tolerated set is a whitelist: each rule names one check *and* the exact
message that marks its failure as a quota/availability response rather than a
verdict on the code. Anything else — including any other failure from the same
check — still fails CI normally.

Adding a new exception
----------------------
Append a :class:`ToleratedFailure` to :data:`TOLERATED_FAILURES`::

    ToleratedFailure(
        check="some-bot",
        description="quota exceeded",
        reason="the bot's plan limit, not a code defect",
    )

or, without waiting for a release, set the environment variable::

    CLAUDETM_TOLERATED_CHECK_FAILURES="some-bot=quota exceeded;other-bot=busy"

Both sides of a rule are matched on stripped, lower-cased text.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

#: Environment variable holding extra rules as ``check=description`` pairs
#: separated by ``;`` (or newlines). Merged with :data:`TOLERATED_FAILURES`.
TOLERATED_FAILURES_ENV = "CLAUDETM_TOLERATED_CHECK_FAILURES"


@dataclass(frozen=True)
class ToleratedFailure:
    """One tolerated check failure.

    Attributes:
        check: Status-check context or check-run name (case-insensitive).
        description: The exact failure description to tolerate (case-insensitive).
            A check failing with any *other* description is a real failure.
        reason: Why it is safe to ignore. Shown when the failure is discounted.
    """

    check: str
    description: str
    reason: str = ""

    def matches(self, name: str, description: str) -> bool:
        """Report whether this rule covers a (name, description) pair.

        Args:
            name: Normalized (stripped, lower-cased) check name.
            description: Normalized (stripped, lower-cased) failure description.

        Returns:
            True if both sides match this rule.
        """
        return self.check.lower() == name and self.description.lower() == description


#: The built-in exceptions. Extend this tuple to tolerate another check.
TOLERATED_FAILURES: tuple[ToleratedFailure, ...] = (
    ToleratedFailure(
        check="CodeRabbit",
        description="Review rate limited",
        reason="CodeRabbit review quota, not a verdict on the code",
    ),
)


def _env_rules() -> tuple[ToleratedFailure, ...]:
    """Parse extra rules from :data:`TOLERATED_FAILURES_ENV`.

    Malformed entries (no ``=``, empty side) are skipped rather than raising —
    a typo in an env var must not break CI evaluation.

    Returns:
        Rules declared in the environment, empty if the variable is unset.
    """
    raw = os.environ.get(TOLERATED_FAILURES_ENV, "")
    rules = []
    for entry in raw.replace("\n", ";").split(";"):
        check, sep, description = entry.partition("=")
        if not sep or not check.strip() or not description.strip():
            continue
        rules.append(
            ToleratedFailure(
                check=check.strip(),
                description=description.strip(),
                reason=f"declared in ${TOLERATED_FAILURES_ENV}",
            )
        )
    return tuple(rules)


def tolerated_reason(check: dict[str, Any]) -> str | None:
    """Return why a failing check may be ignored, or None if it may not.

    Args:
        check: Normalized check detail dict (see ``_parse_check_contexts``).
            Only ``StatusContext`` entries carry a ``description``; ``CheckRun``
            entries never match and are always treated as real failures.

    Returns:
        The rule's ``reason`` (possibly empty) when a rule matches, else None.
    """
    name = (check.get("name") or check.get("context") or "").strip().lower()
    description = (check.get("description") or "").strip().lower()
    if not name or not description:
        return None
    for rule in TOLERATED_FAILURES + _env_rules():
        if rule.matches(name, description):
            return rule.reason
    return None


def is_tolerated_failure(check: dict[str, Any]) -> bool:
    """Report whether a failing check may be ignored.

    Args:
        check: Normalized check detail dict.

    Returns:
        True if a tolerance rule covers this check and description.
    """
    return tolerated_reason(check) is not None


def is_failed_check(check: dict[str, Any]) -> bool:
    """Report whether a check counts as a real CI failure.

    Args:
        check: Normalized check detail dict.

    Returns:
        True if the check concluded in a failure state and is not tolerated.
    """
    conclusion = (check.get("conclusion") or "").upper()
    if conclusion not in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT"):
        return False
    return not is_tolerated_failure(check)


__all__ = [
    "TOLERATED_FAILURES",
    "TOLERATED_FAILURES_ENV",
    "ToleratedFailure",
    "is_failed_check",
    "is_tolerated_failure",
    "tolerated_reason",
]
