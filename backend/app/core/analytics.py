"""Lightweight analytics event logging using structured logging infrastructure."""
import logging

_logger = logging.getLogger("app.analytics")


def log_event(event_name: str, user_id: int | None = None, **kwargs) -> None:
    """Log a business analytics event.

    Uses the existing structured logging pipeline so events are captured
    by whatever log sink is configured (stdout / JSON / external).
    """
    parts = [f"event={event_name}"]
    if user_id is not None:
        parts.append(f"user_id={user_id}")
    for k, v in kwargs.items():
        parts.append(f"{k}={v}")
    _logger.info(" | ".join(parts))
