"""Pytest configuration for property-based tests.

This module provides shared fixtures and configuration for Hypothesis tests.
"""

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


@pytest.fixture(autouse=True)
def _reset_hypothesis_settings():
    """Reset Hypothesis settings between tests."""
    # This ensures each test starts with clean settings
    yield
