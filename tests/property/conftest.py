"""Pytest configuration for property-based tests.

This module provides shared fixtures and configuration for Hypothesis tests.
"""

import os

import pytest
from hypothesis import Phase, Verbosity, settings

# Configure default Hypothesis settings for the test suite
settings.register_profile(
    "ci",
    max_examples=100,
    deadline=None,  # Disable deadline in CI to avoid flaky tests
    suppress_health_check=[],
    verbosity=Verbosity.normal,
)

settings.register_profile(
    "dev",
    max_examples=50,
    deadline=None,
    verbosity=Verbosity.verbose,
)

settings.register_profile(
    "quick",
    max_examples=10,
    deadline=None,
    phases=[Phase.generate],  # Skip shrinking for faster runs
)

settings.register_profile(
    "thorough",
    max_examples=500,
    deadline=None,
    verbosity=Verbosity.normal,
)

# Load profile from environment variable if set
_profile = os.environ.get("HYPOTHESIS_PROFILE", "default")
if _profile in ("ci", "dev", "quick", "thorough"):
    settings.load_profile(_profile)


@pytest.fixture(autouse=True)
def _reset_hypothesis_settings():
    """Reset Hypothesis settings between tests."""
    # This ensures each test starts with clean settings
    yield


def pytest_collection_modifyitems(config, items):
    """Mark property tests and give them room to run.

    A property test is tens-to-hundreds of examples in a single test item, so
    the suite-wide ``--timeout=2`` (sized for one-shot unit tests) is the wrong
    budget: under `pytest -n auto`, a filesystem-backed property like the
    mailbox's — up to 30 locked, atomically-written messages per example — can
    blow through 2s on a loaded worker and fail as a timeout rather than on its
    own merits. 60s is still far below any real hang.
    """
    for item in items:
        if "property" in str(item.fspath):
            item.add_marker(pytest.mark.property)
            if item.get_closest_marker("timeout") is None:
                item.add_marker(pytest.mark.timeout(60))
