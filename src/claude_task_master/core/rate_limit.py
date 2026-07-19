"""Rate Limiting Configuration - Configurable exponential backoff for API calls."""

import random
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RateLimitConfig(BaseModel):
    """Configuration for API rate limiting and exponential backoff.

    This configuration controls how the system handles API rate limiting,
    including retry logic for transient errors.

    Attributes:
        max_retries: Maximum number of retry attempts for rate-limited requests.
        initial_backoff: Initial backoff time in seconds before first retry.
        max_backoff: Maximum backoff time in seconds between retries.
        backoff_multiplier: Exponential multiplier for backoff time between retries.
    """

    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum number of retry attempts (0-10)",
    )
    initial_backoff: float = Field(
        default=1.0,
        gt=0,
        le=60,
        description="Initial backoff time in seconds (0.1-60)",
    )
    max_backoff: float = Field(
        default=30.0,
        gt=0,
        le=300,
        description="Maximum backoff time in seconds (0.1-300)",
    )
    backoff_multiplier: float = Field(
        default=2.0,
        gt=1,
        le=10,
        description="Exponential backoff multiplier (1-10)",
    )

    @field_validator("max_backoff")
    @classmethod
    def validate_max_backoff(cls, v: float, info: Any) -> float:
        """Ensure max_backoff is >= initial_backoff."""
        if "initial_backoff" in info.data and v < info.data["initial_backoff"]:
            raise ValueError("max_backoff must be >= initial_backoff")
        return v

    @classmethod
    def default(cls) -> "RateLimitConfig":
        """Return default rate limit configuration."""
        return cls()

    @classmethod
    def aggressive(cls) -> "RateLimitConfig":
        """Return aggressive rate limiting (more retries, longer backoff).

        Useful for heavy workloads or when hitting rate limits frequently.
        """
        return cls(
            max_retries=5,
            initial_backoff=2.0,
            max_backoff=60.0,
            backoff_multiplier=2.5,
        )

    @classmethod
    def conservative(cls) -> "RateLimitConfig":
        """Return conservative rate limiting (fewer retries, shorter backoff).

        Useful for quick operations or when rate limits are not expected.
        """
        return cls(
            max_retries=1,
            initial_backoff=0.5,
            max_backoff=10.0,
            backoff_multiplier=1.5,
        )

    @classmethod
    def from_dict(cls, config: dict | None) -> "RateLimitConfig":
        """Create RateLimitConfig from dictionary.

        Args:
            config: Optional dictionary with rate limit settings.
                   Uses defaults if None or missing keys.

        Returns:
            RateLimitConfig instance.

        Raises:
            ValueError: If configuration values are invalid.
        """
        if config is None:
            return cls.default()
        return cls(**{k: v for k, v in config.items() if k in cls.model_fields})

    def to_dict(self) -> dict:
        """Convert configuration to dictionary."""
        return self.model_dump()

    def _base_backoff(self, attempt: int) -> float:
        """Deterministic (no-jitter) backoff for a given attempt.

        Used by get_total_max_time() for planning and by calculate_backoff()
        as the ceiling before jitter is applied.

        Args:
            attempt: Attempt number (0-indexed).

        Returns:
            Deterministic backoff in seconds, clamped to max_backoff.
        """
        if attempt < 0:
            return 0
        backoff = self.initial_backoff * (self.backoff_multiplier**attempt)
        return min(backoff, self.max_backoff)

    def calculate_backoff(self, attempt: int) -> float:
        """Calculate backoff time for given attempt number with decorrelated jitter.

        Jitter spreads simultaneous retries across concurrent instances so they
        don't all hit the API in lockstep.  The random factor is in [0.5, 1.0]
        so the returned value is always between half and the full deterministic
        ceiling — callers never wait longer than the configured max_backoff.

        Args:
            attempt: Attempt number (0-indexed).

        Returns:
            Jittered backoff time in seconds.
        """
        base = self._base_backoff(attempt)
        if base == 0:
            return 0
        # Multiply by [0.5, 1.0] — expected value is 0.75× the deterministic
        # ceiling, maximum is 1.0× (so the cap is never exceeded).
        return base * (0.5 + 0.5 * random.random())

    def get_total_max_time(self) -> float:
        """Calculate total maximum time for all retries (deterministic, no jitter).

        Returns:
            Sum of all deterministic backoff times in seconds.
        """
        total = 0.0
        for attempt in range(self.max_retries):
            total += self._base_backoff(attempt)
        return total

    def __str__(self) -> str:
        """Return human-readable string representation."""
        return (
            f"RateLimitConfig(max_retries={self.max_retries}, "
            f"initial_backoff={self.initial_backoff}s, "
            f"max_backoff={self.max_backoff}s, "
            f"multiplier={self.backoff_multiplier}x, "
            f"max_total_time={self.get_total_max_time():.1f}s)"
        )
