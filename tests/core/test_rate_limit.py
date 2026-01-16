"""Tests for rate_limit.py - rate limiting configuration."""

import pytest
from pydantic import ValidationError

from claude_task_master.core.rate_limit import RateLimitConfig


class TestRateLimitConfigDefaults:
    """Tests for RateLimitConfig default values."""

    def test_default_initialization(self):
        """Test creating RateLimitConfig with defaults."""
        config = RateLimitConfig()
        assert config.max_retries == 3
        assert config.initial_backoff == 1.0
        assert config.max_backoff == 30.0
        assert config.backoff_multiplier == 2.0

    def test_default_class_method(self):
        """Test RateLimitConfig.default() class method."""
        config = RateLimitConfig.default()
        assert config.max_retries == 3
        assert config.initial_backoff == 1.0
        assert config.max_backoff == 30.0
        assert config.backoff_multiplier == 2.0

    def test_aggressive_preset(self):
        """Test aggressive rate limiting preset."""
        config = RateLimitConfig.aggressive()
        assert config.max_retries == 5
        assert config.initial_backoff == 2.0
        assert config.max_backoff == 60.0
        assert config.backoff_multiplier == 2.5

    def test_conservative_preset(self):
        """Test conservative rate limiting preset."""
        config = RateLimitConfig.conservative()
        assert config.max_retries == 1
        assert config.initial_backoff == 0.5
        assert config.max_backoff == 10.0
        assert config.backoff_multiplier == 1.5


class TestRateLimitConfigValidation:
    """Tests for RateLimitConfig validation."""

    def test_max_retries_bounds(self):
        """Test max_retries validation (0-10)."""
        # Valid values
        RateLimitConfig(max_retries=0)
        RateLimitConfig(max_retries=5)
        RateLimitConfig(max_retries=10)

        # Invalid values
        with pytest.raises(ValidationError):
            RateLimitConfig(max_retries=-1)
        with pytest.raises(ValidationError):
            RateLimitConfig(max_retries=11)

    def test_initial_backoff_bounds(self):
        """Test initial_backoff validation (> 0, <= 60)."""
        # Valid values
        RateLimitConfig(initial_backoff=0.1)
        RateLimitConfig(initial_backoff=30.0)
        RateLimitConfig(initial_backoff=60.0)

        # Invalid values
        with pytest.raises(ValidationError):
            RateLimitConfig(initial_backoff=0)  # Must be > 0
        with pytest.raises(ValidationError):
            RateLimitConfig(initial_backoff=61)

    def test_max_backoff_bounds(self):
        """Test max_backoff validation (> 0, <= 300, >= initial_backoff)."""
        # Valid values
        RateLimitConfig(initial_backoff=0.1, max_backoff=0.1)  # Equal to initial_backoff
        RateLimitConfig(max_backoff=150.0)
        RateLimitConfig(max_backoff=300.0)

        # Invalid values
        with pytest.raises(ValidationError):
            RateLimitConfig(max_backoff=0)  # Must be > 0
        with pytest.raises(ValidationError):
            RateLimitConfig(max_backoff=301)
        with pytest.raises(ValidationError):
            RateLimitConfig(initial_backoff=10.0, max_backoff=0.1)  # Must be >= initial_backoff

    def test_backoff_multiplier_bounds(self):
        """Test backoff_multiplier validation (> 1, <= 10)."""
        # Valid values
        RateLimitConfig(backoff_multiplier=1.1)
        RateLimitConfig(backoff_multiplier=5.0)
        RateLimitConfig(backoff_multiplier=10.0)

        # Invalid values
        with pytest.raises(ValidationError):
            RateLimitConfig(backoff_multiplier=1)  # Must be > 1
        with pytest.raises(ValidationError):
            RateLimitConfig(backoff_multiplier=10.1)

    def test_max_backoff_greater_than_initial_backoff(self):
        """Test that max_backoff must be >= initial_backoff."""
        # Valid
        RateLimitConfig(initial_backoff=10.0, max_backoff=10.0)
        RateLimitConfig(initial_backoff=10.0, max_backoff=20.0)

        # Invalid
        with pytest.raises(ValidationError) as exc_info:
            RateLimitConfig(initial_backoff=20.0, max_backoff=10.0)
        assert "max_backoff must be >= initial_backoff" in str(exc_info.value)


class TestRateLimitConfigBackoffCalculation:
    """Tests for backoff calculation."""

    def test_calculate_backoff_first_attempt(self):
        """Test backoff time for first retry attempt."""
        config = RateLimitConfig(initial_backoff=1.0, max_backoff=30.0)
        backoff = config.calculate_backoff(0)
        assert backoff == 1.0

    def test_calculate_backoff_exponential(self):
        """Test exponential backoff calculation."""
        config = RateLimitConfig(
            initial_backoff=1.0,
            max_backoff=100.0,
            backoff_multiplier=2.0,
        )
        assert config.calculate_backoff(0) == 1.0
        assert config.calculate_backoff(1) == 2.0
        assert config.calculate_backoff(2) == 4.0
        assert config.calculate_backoff(3) == 8.0
        assert config.calculate_backoff(4) == 16.0

    def test_calculate_backoff_capped_at_max(self):
        """Test that backoff time is capped at max_backoff."""
        config = RateLimitConfig(
            initial_backoff=1.0,
            max_backoff=10.0,
            backoff_multiplier=2.0,
        )
        assert config.calculate_backoff(0) == 1.0
        assert config.calculate_backoff(1) == 2.0
        assert config.calculate_backoff(2) == 4.0
        assert config.calculate_backoff(3) == 8.0
        assert config.calculate_backoff(4) == 10.0  # Capped
        assert config.calculate_backoff(5) == 10.0  # Still capped

    def test_calculate_backoff_negative_attempt(self):
        """Test backoff calculation with negative attempt number."""
        config = RateLimitConfig()
        assert config.calculate_backoff(-1) == 0

    def test_calculate_backoff_different_multiplier(self):
        """Test backoff with different multiplier."""
        config = RateLimitConfig(
            initial_backoff=2.0,
            max_backoff=100.0,
            backoff_multiplier=1.5,
        )
        assert config.calculate_backoff(0) == 2.0
        assert config.calculate_backoff(1) == 3.0
        assert config.calculate_backoff(2) == 4.5
        assert config.calculate_backoff(3) == 6.75


class TestRateLimitConfigTotalTime:
    """Tests for total maximum time calculation."""

    def test_total_max_time_default(self):
        """Test total max time with default config."""
        config = RateLimitConfig()
        # 3 retries: 1.0 + 2.0 + 4.0 = 7.0 seconds
        total = config.get_total_max_time()
        assert total == pytest.approx(7.0)

    def test_total_max_time_aggressive(self):
        """Test total max time with aggressive config."""
        config = RateLimitConfig.aggressive()
        # 5 retries: 2.0 + 5.0 + 12.5 + 31.25 + 60.0 = 110.75 seconds
        # But last two are capped at 60.0
        total = config.get_total_max_time()
        assert total == 2.0 + 5.0 + 12.5 + 31.25 + 60.0

    def test_total_max_time_conservative(self):
        """Test total max time with conservative config."""
        config = RateLimitConfig.conservative()
        # 1 retry: 0.5 seconds
        total = config.get_total_max_time()
        assert total == pytest.approx(0.5)

    def test_total_max_time_no_retries(self):
        """Test total max time with no retries."""
        config = RateLimitConfig(max_retries=0)
        total = config.get_total_max_time()
        assert total == 0


class TestRateLimitConfigSerialization:
    """Tests for serialization and deserialization."""

    def test_to_dict(self):
        """Test converting RateLimitConfig to dictionary."""
        config = RateLimitConfig(max_retries=5, initial_backoff=2.0)
        d = config.to_dict()

        assert isinstance(d, dict)
        assert d["max_retries"] == 5
        assert d["initial_backoff"] == 2.0
        assert d["max_backoff"] == 30.0
        assert d["backoff_multiplier"] == 2.0

    def test_from_dict_full(self):
        """Test creating RateLimitConfig from full dictionary."""
        d = {
            "max_retries": 5,
            "initial_backoff": 2.0,
            "max_backoff": 60.0,
            "backoff_multiplier": 2.5,
        }
        config = RateLimitConfig.from_dict(d)

        assert config.max_retries == 5
        assert config.initial_backoff == 2.0
        assert config.max_backoff == 60.0
        assert config.backoff_multiplier == 2.5

    def test_from_dict_partial(self):
        """Test creating RateLimitConfig from partial dictionary."""
        d = {"max_retries": 5, "initial_backoff": 2.0}
        config = RateLimitConfig.from_dict(d)

        # Specified values
        assert config.max_retries == 5
        assert config.initial_backoff == 2.0
        # Default values
        assert config.max_backoff == 30.0
        assert config.backoff_multiplier == 2.0

    def test_from_dict_none(self):
        """Test creating RateLimitConfig from None dictionary."""
        config = RateLimitConfig.from_dict(None)
        assert config == RateLimitConfig.default()

    def test_from_dict_empty(self):
        """Test creating RateLimitConfig from empty dictionary."""
        config = RateLimitConfig.from_dict({})
        assert config == RateLimitConfig.default()

    def test_from_dict_ignores_unknown_keys(self):
        """Test that from_dict ignores unknown keys."""
        d = {
            "max_retries": 5,
            "unknown_key": "ignored",
            "another_unknown": 123,
        }
        config = RateLimitConfig.from_dict(d)
        assert config.max_retries == 5
        # No error raised


class TestRateLimitConfigStringRepresentation:
    """Tests for string representation."""

    def test_str_representation(self):
        """Test string representation of RateLimitConfig."""
        config = RateLimitConfig.default()
        s = str(config)

        assert "RateLimitConfig" in s
        assert "max_retries=3" in s
        assert "initial_backoff=1.0s" in s
        assert "max_backoff=30.0s" in s
        assert "multiplier=2.0x" in s
        assert "max_total_time" in s

    def test_str_representation_custom(self):
        """Test string representation with custom values."""
        config = RateLimitConfig(
            max_retries=5,
            initial_backoff=2.0,
            max_backoff=60.0,
            backoff_multiplier=2.5,
        )
        s = str(config)

        assert "max_retries=5" in s
        assert "initial_backoff=2.0s" in s
        assert "max_backoff=60.0s" in s
        assert "multiplier=2.5x" in s


class TestRateLimitConfigEquality:
    """Tests for equality comparison."""

    def test_equal_configs(self):
        """Test equality of identical configs."""
        config1 = RateLimitConfig(max_retries=5, initial_backoff=2.0)
        config2 = RateLimitConfig(max_retries=5, initial_backoff=2.0)

        assert config1 == config2

    def test_unequal_configs(self):
        """Test inequality of different configs."""
        config1 = RateLimitConfig(max_retries=5)
        config2 = RateLimitConfig(max_retries=3)

        assert config1 != config2

    def test_default_equals_explicit_defaults(self):
        """Test that default() equals explicitly specified defaults."""
        config1 = RateLimitConfig.default()
        config2 = RateLimitConfig(
            max_retries=3,
            initial_backoff=1.0,
            max_backoff=30.0,
            backoff_multiplier=2.0,
        )

        assert config1 == config2
