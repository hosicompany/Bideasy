from __future__ import annotations

import pytest
from bideasy_creative_runner.config import RunnerConfig
from bideasy_creative_runner.errors import ConfigurationError


def _required_env(monkeypatch) -> None:
    monkeypatch.setenv("CREATIVE_RUNNER_TOKEN", "local-service-token")
    monkeypatch.setenv(
        "HIGGSFIELD_WORKSPACE_ID", "3e8ac169-38f2-4c0f-b036-7132fad579a0"
    )


@pytest.mark.parametrize(
    "api_base",
    [
        "https://user:secret@api.bideasy.kr",
        "https://api.bideasy.kr?target=elsewhere",
        "https://api.bideasy.kr:not-a-port",
    ],
)
def test_api_base_must_be_a_credential_free_https_origin(monkeypatch, api_base):
    _required_env(monkeypatch)
    monkeypatch.setenv("CREATIVE_RUNNER_API_BASE", api_base)

    with pytest.raises(ConfigurationError, match="HTTPS origin"):
        RunnerConfig.from_env()


@pytest.mark.parametrize("prefix", ["relative", "/api//runner", "/api/../admin"])
def test_api_prefix_rejects_ambiguous_paths(monkeypatch, prefix):
    _required_env(monkeypatch)
    monkeypatch.setenv("CREATIVE_RUNNER_API_PREFIX", prefix)

    with pytest.raises(ConfigurationError, match="absolute URL path"):
        RunnerConfig.from_env()


def test_higgsfield_wait_timeout_is_one_bounded_duration(monkeypatch):
    _required_env(monkeypatch)
    monkeypatch.setenv("CREATIVE_RUNNER_HIGGSFIELD_WAIT_TIMEOUT", "--workspace")

    with pytest.raises(ConfigurationError, match="bounded duration"):
        RunnerConfig.from_env()
