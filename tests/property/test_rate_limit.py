"""Property-based tests for RateLimitConfig.

Tests the mathematical properties of exponential backoff calculations.
"""

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from claude_task_master.core.rate_limit import RateLimitConfig


class TestRateLimitConfigProperties:
    """Property-based tests for RateLimitConfig."""

    @given(
        max_retries=st.integers(min_value=0, max_value=5),
        initial_backoff=st.floats(min_value=0.1, max_value=10, allow_nan=False),
        backoff_multiplier=st.floats(min_value=1.01, max_value=3, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_backoff_monotonically_increasing(
        self, max_retries: int, initial_backoff: float, backoff_multiplier: float
    ):
        """Backoff times should be monotonically increasing until hitting max."""
        # Calculate max_backoff and clamp to valid range [initial_backoff, 300]
        max_backoff = min(300, initial_backoff * (backoff_multiplier**max_retries))
        config = RateLimitConfig(
            max_retries=max_retries,
            initial_backoff=initial_backoff,
            max_backoff=max_backoff,
            backoff_multiplier=backoff_multiplier,
        )

        prev_backoff = 0.0
        for attempt in range(max_retries):
            current_backoff = config.calculate_backoff(attempt)
            assert current_backoff >= prev_backoff
            prev_backoff = current_backoff

    @given(
        max_retries=st.integers(min_value=1, max_value=10),
        initial_backoff=st.floats(min_value=0.1, max_value=60, allow_nan=False),
        backoff_multiplier=st.floats(min_value=1.01, max_value=10, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_backoff_never_exceeds_max(
        self, max_retries: int, initial_backoff: float, backoff_multiplier: float
    ):
        """Backoff should never exceed max_backoff."""
        max_backoff = initial_backoff * 2  # Set max_backoff to limit growth
        config = RateLimitConfig(
            max_retries=max_retries,
            initial_backoff=initial_backoff,
            max_backoff=max_backoff,
            backoff_multiplier=backoff_multiplier,
        )

        for attempt in range(max_retries + 5):  # Test beyond max_retries
            backoff = config.calculate_backoff(attempt)
            assert backoff <= max_backoff

    @given(
        max_retries=st.integers(min_value=0, max_value=10),
        initial_backoff=st.floats(
            min_value=0.1, max_value=30, allow_nan=False
        ),  # Limit to 30 so 10x stays under 300
        backoff_multiplier=st.floats(min_value=1.01, max_value=5, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_first_attempt_is_initial_backoff(
        self, max_retries: int, initial_backoff: float, backoff_multiplier: float
    ):
        """First attempt (0) should always return initial_backoff."""
        max_backoff = min(300, initial_backoff * 10)  # Clamp to valid range
        config = RateLimitConfig(
            max_retries=max_retries,
            initial_backoff=initial_backoff,
            max_backoff=max_backoff,
            backoff_multiplier=backoff_multiplier,
        )

        assert config.calculate_backoff(0) == pytest.approx(initial_backoff)

    @given(
        max_retries=st.integers(min_value=1, max_value=5),
        initial_backoff=st.floats(min_value=0.1, max_value=10, allow_nan=False),
        backoff_multiplier=st.floats(min_value=1.01, max_value=3, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_total_max_time_is_sum_of_backoffs(
        self, max_retries: int, initial_backoff: float, backoff_multiplier: float
    ):
        """Total max time should equal sum of all backoff times."""
        max_backoff = min(300, initial_backoff * (backoff_multiplier**max_retries))
        config = RateLimitConfig(
            max_retries=max_retries,
            initial_backoff=initial_backoff,
            max_backoff=max_backoff,
            backoff_multiplier=backoff_multiplier,
        )

        expected_total = sum(config.calculate_backoff(i) for i in range(max_retries))
        assert config.get_total_max_time() == pytest.approx(expected_total)

    @given(attempt=st.integers(min_value=-100, max_value=-1))
    @settings(max_examples=50)
    def test_negative_attempt_returns_zero(self, attempt: int):
        """Negative attempt numbers should return 0."""
        config = RateLimitConfig()
        assert config.calculate_backoff(attempt) == 0

    @given(
        initial_backoff=st.floats(min_value=0.1, max_value=60, allow_nan=False),
        max_backoff=st.floats(min_value=0.1, max_value=300, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_max_backoff_must_be_gte_initial(self, initial_backoff: float, max_backoff: float):
        """max_backoff must be >= initial_backoff."""
        assume(max_backoff < initial_backoff)  # Only test invalid cases

        with pytest.raises(ValueError, match="max_backoff must be >= initial_backoff"):
            RateLimitConfig(
                initial_backoff=initial_backoff,
                max_backoff=max_backoff,
            )

    @given(
        config_dict=st.fixed_dictionaries(
            {},
            optional={
                "max_retries": st.integers(min_value=0, max_value=10),
                "initial_backoff": st.floats(
                    min_value=0.1, max_value=30, allow_nan=False
                ),  # Limit so 10x stays under 300
                "backoff_multiplier": st.floats(min_value=1.01, max_value=5, allow_nan=False),
            },
        )
    )
    @settings(max_examples=100)
    def test_from_dict_produces_valid_config(self, config_dict: dict):
        """from_dict should always produce a valid configuration."""
        # Add max_backoff if initial_backoff is present to ensure validity
        if "initial_backoff" in config_dict:
            config_dict["max_backoff"] = min(300, config_dict["initial_backoff"] * 10)

        config = RateLimitConfig.from_dict(config_dict)

        assert config.max_retries >= 0
        assert config.max_retries <= 10
        assert config.initial_backoff > 0
        assert config.max_backoff >= config.initial_backoff
        assert config.backoff_multiplier > 1

    def test_preset_configurations_are_valid(self):
        """All preset configurations should be valid."""
        configs = [
            RateLimitConfig.default(),
            RateLimitConfig.aggressive(),
            RateLimitConfig.conservative(),
        ]

        for config in configs:
            assert config.max_retries >= 0
            assert config.initial_backoff > 0
            assert config.max_backoff >= config.initial_backoff
            assert config.backoff_multiplier > 1

            # Should be able to calculate backoff without error
            for i in range(config.max_retries + 1):
                backoff = config.calculate_backoff(i)
                assert backoff >= 0
                assert backoff <= config.max_backoff
