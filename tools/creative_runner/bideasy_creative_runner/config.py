"""Environment-only runner configuration (no secret values are committed)."""

from __future__ import annotations

import os
import re
import socket
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .errors import ConfigurationError

PINNED_HIGGSFIELD_VERSION = "1.1.23"
DEFAULT_BRAND_POLICY_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "CREATIVE_BRAND_KIT.json"
)
DEFAULT_FONT_DIR = Path(__file__).resolve().parents[3] / "frontend" / "assets" / "fonts"
DEFAULT_BRAND_ASSET_ROOT = (
    Path(__file__).resolve().parents[3] / "infra" / "nginx" / "html"
)


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be positive")
    return value


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be positive")
    return value


@dataclass(frozen=True)
class RunnerConfig:
    api_base: str
    api_prefix: str
    service_token: str = field(repr=False)
    workspace_id: str
    runner_id: str = socket.gethostname()
    higgsfield_bin: str = "higgsfield"
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    poll_seconds: float = 15.0
    heartbeat_seconds: float = 60.0
    request_timeout_seconds: float = 30.0
    command_timeout_seconds: float = 2100.0
    wait_timeout: str = "30m"
    max_asset_bytes: int = 150 * 1024 * 1024
    input_hosts: tuple[str, ...] = ("bideasy.kr", "api.bideasy.kr")
    retry_backoffs: tuple[float, ...] = (30.0, 120.0, 300.0)
    brand_policy_path: Path = DEFAULT_BRAND_POLICY_PATH
    font_dir: Path = DEFAULT_FONT_DIR
    brand_asset_root: Path = DEFAULT_BRAND_ASSET_ROOT
    remote_brand_kit_id: str | None = None

    @property
    def runner_api_url(self) -> str:
        return f"{self.api_base.rstrip('/')}/{self.api_prefix.strip('/')}"

    @classmethod
    def from_env(cls) -> RunnerConfig:
        api_base = (
            os.getenv("CREATIVE_RUNNER_API_BASE", "https://api.bideasy.kr")
            .strip()
            .rstrip("/")
        )
        try:
            parsed = urlparse(api_base)
            _port = parsed.port
        except ValueError as exc:
            raise ConfigurationError(
                "CREATIVE_RUNNER_API_BASE must be a valid HTTPS origin"
            ) from exc
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.path not in ("", "/")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ConfigurationError(
                "CREATIVE_RUNNER_API_BASE must be an HTTPS origin without a path"
            )

        token = os.getenv("CREATIVE_RUNNER_TOKEN", "").strip()
        if not token:
            raise ConfigurationError("CREATIVE_RUNNER_TOKEN is required")
        workspace_id = os.getenv("HIGGSFIELD_WORKSPACE_ID", "").strip()
        if not workspace_id:
            raise ConfigurationError("HIGGSFIELD_WORKSPACE_ID is required")

        configured_hosts = {
            item.strip().lower().rstrip(".")
            for item in os.getenv(
                "CREATIVE_RUNNER_INPUT_HOSTS", "bideasy.kr,api.bideasy.kr"
            ).split(",")
            if item.strip()
        }
        configured_hosts.add(parsed.hostname.lower().rstrip("."))

        prefix = os.getenv(
            "CREATIVE_RUNNER_API_PREFIX", "/api/v1/creative-runner"
        ).strip()
        if (
            not prefix.startswith("/")
            or "?" in prefix
            or "#" in prefix
            or "//" in prefix
            or ".." in prefix.split("/")
        ):
            raise ConfigurationError(
                "CREATIVE_RUNNER_API_PREFIX must be an absolute URL path"
            )

        wait_timeout = (
            os.getenv("CREATIVE_RUNNER_HIGGSFIELD_WAIT_TIMEOUT", "30m").strip() or "30m"
        )
        if not re.fullmatch(r"[1-9][0-9]{0,3}[smh]", wait_timeout):
            raise ConfigurationError(
                "CREATIVE_RUNNER_HIGGSFIELD_WAIT_TIMEOUT must be a bounded duration such as 30m"
            )

        return cls(
            api_base=api_base,
            api_prefix=prefix,
            service_token=token,
            workspace_id=workspace_id,
            runner_id=os.getenv("CREATIVE_RUNNER_ID", socket.gethostname()).strip()
            or socket.gethostname(),
            higgsfield_bin=os.getenv("HIGGSFIELD_BIN", "higgsfield").strip()
            or "higgsfield",
            ffmpeg_bin=os.getenv("CREATIVE_RUNNER_FFMPEG_BIN", "ffmpeg").strip()
            or "ffmpeg",
            ffprobe_bin=os.getenv("CREATIVE_RUNNER_FFPROBE_BIN", "ffprobe").strip()
            or "ffprobe",
            poll_seconds=_positive_float("CREATIVE_RUNNER_POLL_SECONDS", 15),
            heartbeat_seconds=_positive_float("CREATIVE_RUNNER_HEARTBEAT_SECONDS", 60),
            request_timeout_seconds=_positive_float(
                "CREATIVE_RUNNER_REQUEST_TIMEOUT_SECONDS", 30
            ),
            command_timeout_seconds=_positive_float(
                "CREATIVE_RUNNER_COMMAND_TIMEOUT_SECONDS", 2100
            ),
            wait_timeout=wait_timeout,
            max_asset_bytes=_positive_int(
                "CREATIVE_RUNNER_MAX_ASSET_BYTES", 150 * 1024 * 1024
            ),
            input_hosts=tuple(sorted(configured_hosts)),
            brand_policy_path=Path(
                os.getenv("CREATIVE_BRAND_POLICY_PATH", str(DEFAULT_BRAND_POLICY_PATH))
            ).expanduser(),
            font_dir=Path(
                os.getenv("CREATIVE_RUNNER_FONT_DIR", str(DEFAULT_FONT_DIR))
            ).expanduser(),
            brand_asset_root=Path(
                os.getenv("CREATIVE_BRAND_ASSET_ROOT", str(DEFAULT_BRAND_ASSET_ROOT))
            ).expanduser(),
            # Reserved for a future explicitly-approved DTC Ads path. It is never
            # inferred from the remote fetch result or sent by today's allowlisted jobs.
            remote_brand_kit_id=os.getenv("HIGGSFIELD_BRAND_KIT_ID", "").strip()
            or None,
        )
