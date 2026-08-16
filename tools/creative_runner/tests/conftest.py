from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOL_ROOT = Path(__file__).resolve().parents[1]
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

from bideasy_creative_runner.config import RunnerConfig


@pytest.fixture
def runner_config() -> RunnerConfig:
    return RunnerConfig(
        api_base="https://api.bideasy.kr",
        api_prefix="/api/v1/creative-runner",
        service_token="runner-test-token",
        workspace_id="3e8ac169-38f2-4c0f-b036-7132fad579a0",
        runner_id="test-mac",
        higgsfield_bin="/fake/higgsfield",
        heartbeat_seconds=1,
        command_timeout_seconds=10,
        retry_backoffs=(0.1, 0.2, 0.3),
    )
