"""Typed failures used to report safe attempt states to the BidEasy API."""


class RunnerError(RuntimeError):
    """Base runner failure."""

    retryable = False
    auth_required = False


class ConfigurationError(RunnerError):
    """The local runner configuration is incomplete or unsafe."""


class ApiError(RunnerError):
    """The BidEasy runner API could not complete a request."""


class ApiAuthenticationError(ApiError):
    """The rotating BidEasy runner service token is invalid."""

    auth_required = True


class InvalidJobError(RunnerError):
    """A claimed job is outside the explicit local allowlist."""


class HiggsfieldAuthRequired(RunnerError):
    """The operator must refresh local Higgsfield authentication/workspace state."""

    auth_required = True


class RetryableHiggsfieldError(RunnerError):
    """A 429/5xx/transient upstream error exhausted bounded retries."""

    retryable = True


class HiggsfieldTimeout(RunnerError):
    """A generation timed out and could not safely rejoin a known job."""

    retryable = True


class AssetError(RunnerError):
    """An input, output download, or deterministic derivative is invalid."""
