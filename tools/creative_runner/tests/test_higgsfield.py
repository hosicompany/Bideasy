from __future__ import annotations

import json
import subprocess
from dataclasses import replace

import pytest
from bideasy_creative_runner.api import ClaimedAttempt
from bideasy_creative_runner.assets import LocalAsset
from bideasy_creative_runner.errors import (
    HiggsfieldAuthRequired,
    InvalidJobError,
    RunnerError,
)
from bideasy_creative_runner.higgsfield import HiggsfieldCli


def _attempt(
    job_type="gpt_image_2", params=None, prompt="actual product screen, no text"
):
    return ClaimedAttempt(
        attempt_id=1,
        creative_id="cr_test",
        attempt_no=1,
        job_type=job_type,
        prompt=prompt,
        params=params or {},
        input_assets=(),
        input_hash=None,
        lease_expires_at=None,
        brief_format="blog_hero_16_9",
    )


def test_build_command_is_closed_allowlist_and_never_passes_source_ui_or_voice(
    tmp_path, runner_config
):
    cli = HiggsfieldCli(runner_config)
    source_ui = LocalAsset(tmp_path / "ui.png", "image/png", "source_ui", "a" * 64)
    storyboard = LocalAsset(tmp_path / "story.png", "image/png", "storyboard", "b" * 64)
    voice = LocalAsset(tmp_path / "voice.wav", "audio/wav", "voiceover", "c" * 64)
    command = cli.build_command(
        _attempt(
            "marketing_studio_video",
            {
                "duration": 15,
                "resolution": "1080p",
                "source_ui_timeline": "campaign_15s_v1",
            },
        ),
        [source_ui, storyboard, voice],
    )
    assert command[:4] == [
        "/fake/higgsfield",
        "generate",
        "create",
        "marketing_studio_video",
    ]
    assert "--wait" in command and "--json" in command
    assert command[command.index("--generate_audio") + 1] == "false"
    assert command[command.index("--mode") + 1] == "ugc"
    assert command[command.index("--specific_mode") + 1] == "from_storyboard"
    assert str(storyboard.path) in command
    assert str(source_ui.path) not in command
    assert str(voice.path) not in command
    assert "source_ui_timeline" not in command
    assert "campaign_15s_v1" not in command


def test_brief_format_drives_static_and_reframe_aspect_ratio(tmp_path, runner_config):
    cli = HiggsfieldCli(runner_config)
    static = replace(_attempt("marketing_studio_image"), brief_format="static_4_5")
    static_command = cli.build_command(static, [])
    assert static_command[static_command.index("--aspect_ratio") + 1] == "4:5"

    video = LocalAsset(tmp_path / "composited.mp4", "video/mp4", "reference", "a" * 64)
    reframe = replace(_attempt("reframe", prompt=""), brief_format="video_1_1")
    reframe_command = cli.build_command(reframe, [video])
    assert reframe_command[reframe_command.index("--aspect-ratio") + 1] == "1:1"

    with pytest.raises(InvalidJobError, match="conflicts"):
        cli.build_command(
            replace(static, params={"aspect_ratio": "1:1"}),
            [],
        )


@pytest.mark.parametrize(
    ("job_type", "params"),
    [
        ("shell", {}),
        ("gpt_image_2", {"evil_flag": "$(id)"}),
        ("marketing_studio_video", {"generate_audio": True}),
    ],
)
def test_build_command_rejects_unallowlisted_inputs(job_type, params, runner_config):
    with pytest.raises(InvalidJobError):
        HiggsfieldCli(runner_config).build_command(_attempt(job_type, params), [])


def test_preflight_checks_exact_version_account_and_workspace_without_leaking_token(
    runner_config,
):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if args[1:] == ["--version"]:
            return subprocess.CompletedProcess(
                args, 0, "higgsfield 1.1.23 (build)\n", ""
            )
        if args[1:3] == ["account", "status"]:
            return subprocess.CompletedProcess(
                args, 0, '{"email":"operator@example.com"}', ""
            )
        return subprocess.CompletedProcess(
            args, 0, json.dumps({"id": runner_config.workspace_id}), ""
        )

    HiggsfieldCli(runner_config, run_func=fake_run).preflight()
    assert len(calls) == 3
    assert all(call[1]["env"].get("CREATIVE_RUNNER_TOKEN") is None for call in calls)
    assert all(isinstance(call[0], list) for call in calls)
    assert all("shell" not in call[1] for call in calls)


def test_preflight_turns_403_into_auth_required(runner_config):
    def fake_run(args, **_kwargs):
        if args[1:] == ["--version"]:
            return subprocess.CompletedProcess(args, 0, "higgsfield 1.1.23\n", "")
        return subprocess.CompletedProcess(
            args, 1, "", "Error: request failed with status 403 Forbidden"
        )

    with pytest.raises(HiggsfieldAuthRequired):
        HiggsfieldCli(runner_config, run_func=fake_run).preflight()


def test_preflight_requires_exact_selected_workspace_id(runner_config):
    def fake_run(args, **_kwargs):
        if args[1:] == ["--version"]:
            return subprocess.CompletedProcess(args, 0, "higgsfield 1.1.23\n", "")
        if args[1:3] == ["account", "status"]:
            return subprocess.CompletedProcess(args, 0, '{"authenticated":true}', "")
        return subprocess.CompletedProcess(
            args,
            0,
            json.dumps(
                {
                    "message": f"old={runner_config.workspace_id}; active=another-workspace"
                }
            ),
            "",
        )

    with pytest.raises(HiggsfieldAuthRequired, match="does not match"):
        HiggsfieldCli(runner_config, run_func=fake_run).preflight()


def test_credit_balance_keeps_only_numeric_credits_and_safe_warning(runner_config):
    def available(args, **_kwargs):
        return subprocess.CompletedProcess(
            args,
            0,
            json.dumps(
                {
                    "credits": 1198.5,
                    "email": "operator@example.com",
                    "subscription_plan_type": "private-plan",
                }
            ),
            "",
        )

    balance = HiggsfieldCli(runner_config, run_func=available).credit_balance()
    assert balance.credits == 1198.5
    assert balance.warning is None
    assert "operator@example.com" not in repr(balance)

    def unavailable(args, **_kwargs):
        return subprocess.CompletedProcess(args, 1, "", "HTTP 403 Forbidden")

    missing = HiggsfieldCli(runner_config, run_func=unavailable).credit_balance()
    assert missing.credits is None
    assert missing.warning == "account_authentication_required"


class _ImmediateProcess:
    def __init__(self, args, returncode, stdout, stderr=""):
        self.args = args
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    def communicate(self, timeout=None):
        return self._stdout, self._stderr

    def kill(self):
        self.returncode = -9


def test_429_retries_only_bounded_schedule_with_argv(runner_config):
    outputs = [
        (1, "", "Higgsfield API error (HTTP 429)"),
        (
            0,
            '{"id":"11111111-1111-4111-8111-111111111111","url":"https://cdn.example/final.png"}',
            "",
        ),
    ]
    popen_calls = []

    def popen(args, **kwargs):
        popen_calls.append((args, kwargs))
        code, stdout, stderr = outputs.pop(0)
        return _ImmediateProcess(args, code, stdout, stderr)

    sleeps = []
    beats = []
    result = HiggsfieldCli(
        runner_config, popen_factory=popen, sleeper=sleeps.append
    ).run(_attempt(), [], lambda: beats.append(True))
    assert result.job_id == "11111111-1111-4111-8111-111111111111"
    assert sleeps == [0.1]
    assert beats
    assert len(popen_calls) == 2
    assert all(
        isinstance(call[0], list) and "shell" not in call[1] for call in popen_calls
    )


def test_ambiguous_connection_failure_is_not_retried_without_job_id(runner_config):
    calls = []

    def popen(args, **_kwargs):
        calls.append(args)
        return _ImmediateProcess(args, 1, "", "connection reset by peer")

    with pytest.raises(RunnerError, match="generation failed"):
        HiggsfieldCli(runner_config, popen_factory=popen).run(
            _attempt(), [], lambda: None
        )

    assert len(calls) == 1


def test_timeout_with_job_id_rejoins_instead_of_generating_again(runner_config):
    job_id = "11111111-1111-4111-8111-111111111111"
    outputs = [
        (1, "", f"Timeout after 10m; job {job_id}"),
        (
            0,
            json.dumps(
                {
                    "id": job_id,
                    "status": "completed",
                    "url": "https://cdn.example/final.png",
                }
            ),
            "",
        ),
    ]
    commands = []

    def popen(args, **_kwargs):
        commands.append(args)
        code, stdout, stderr = outputs.pop(0)
        return _ImmediateProcess(args, code, stdout, stderr)

    observed = []
    result = HiggsfieldCli(
        replace(runner_config, retry_backoffs=()), popen_factory=popen
    ).run(_attempt(), [], lambda: None, on_job_id=observed.append)
    assert result.job_id == job_id
    assert observed == [job_id]
    assert commands[0][1:3] == ["generate", "create"]
    assert commands[1][1:3] == ["generate", "get"]
    assert len(commands) == 2


def test_reclaimed_attempt_rejoins_persisted_job_without_new_generation(runner_config):
    job_id = "11111111-1111-4111-8111-111111111111"
    commands = []

    def popen(args, **_kwargs):
        commands.append(args)
        return _ImmediateProcess(
            args,
            0,
            json.dumps(
                {
                    "id": job_id,
                    "status": "completed",
                    "url": "https://cdn.example/final.png",
                }
            ),
        )

    result = HiggsfieldCli(runner_config, popen_factory=popen).run(
        replace(_attempt(), higgsfield_job_id=job_id), [], lambda: None
    )

    assert result.job_id == job_id
    assert len(commands) == 1
    assert commands[0][1:3] == ["generate", "get"]


def test_recovery_auth_failure_becomes_auth_required(runner_config):
    job_id = "11111111-1111-4111-8111-111111111111"

    def popen(args, **_kwargs):
        return _ImmediateProcess(args, 1, "", "Error: HTTP 401 Unauthorized")

    with pytest.raises(HiggsfieldAuthRequired):
        HiggsfieldCli(runner_config, popen_factory=popen).run(
            replace(_attempt(), higgsfield_job_id=job_id), [], lambda: None
        )


def test_brain_activity_uses_cli_video_role_to_build_required_medias(
    tmp_path, runner_config
):
    video = LocalAsset(tmp_path / "creative.mp4", "video/mp4", "reference", "a" * 64)
    command = HiggsfieldCli(runner_config).build_command(
        _attempt("brain_activity", prompt=""), [video]
    )
    assert command[:4] == ["/fake/higgsfield", "generate", "create", "brain_activity"]
    assert command[command.index("--video") + 1] == str(video.path)
    assert (
        "--medias" not in command
    )  # CLI uploads --video and creates the model's medias array.


def test_json_from_output_returns_outermost_object_when_preamble_precedes_json():
    """로그 프리앰블 뒤 JSON — 바깥 객체를 돌려줘야 job id 가 살아남는다.

    회귀: candidates[-1] 이 가장 안쪽 중첩 객체({"url": ...})를 골라 바깥의 id 가 사라졌고,
    fallback 정규식도 못 잡으면 유료 job 을 crash 후 재부착할 수 없었다.
    """
    from bideasy_creative_runner.higgsfield import _extract_job_id, _json_from_output

    job = "6f1c2a3b-4d5e-4f60-8a1b-2c3d4e5f6a7b"
    output = (
        "Authenticating...\nWorkspace: ws-1\n"
        + '{"id": "' + job + '", "results": [{"url": "https://cdn.example/a.mp4"}], "meta": {"n": 1}}'
        + "\nDone.\n"
    )
    value = _json_from_output(output)
    assert isinstance(value, dict)
    assert value.get("id") == job
    assert _extract_job_id(value, output) == job


def test_json_from_output_prefers_first_top_level_object_and_ignores_nested_rescans():
    from bideasy_creative_runner.higgsfield import _json_from_output

    output = 'noise {"a": {"b": {"c": 1}}} trailing {"z": 2}'
    value = _json_from_output(output)
    # 첫 최상위 객체 전체 (안쪽 {"c":1} 도, 뒤의 {"z":2} 도 아님)
    assert value == {"a": {"b": {"c": 1}}}
