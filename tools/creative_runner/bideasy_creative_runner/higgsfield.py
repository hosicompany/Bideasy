"""Strict Higgsfield CLI adapter: pinned version, argv-only allowlist, bounded retries."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .api import ClaimedAttempt
from .assets import LocalAsset
from .config import PINNED_HIGGSFIELD_VERSION, RunnerConfig
from .errors import (
    ConfigurationError,
    HiggsfieldAuthRequired,
    HiggsfieldTimeout,
    InvalidJobError,
    RetryableHiggsfieldError,
    RunnerError,
)

_MODELS = {
    "gpt_image_2",
    "marketing_studio_image",
    "marketing_studio_video",
    "brain_activity",
}
_WORKFLOWS = {"reframe"}
_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_AUTH_MARKERS = (
    "session expired",
    "not authenticated",
    "not logged in",
    "authentication required",
    "login required",
    "401 unauthorized",
    "unauthorized",
    "403 forbidden",
    "no workspace selected",
    "workspace not selected",
)
_RATE_LIMIT_MARKERS = (
    "http 429",
    "status 429",
    "too many requests",
    "rate limit",
    "captcha-delivery",
)
_URL_KEYS = {
    "url",
    "file_url",
    "fileUrl",
    "download_url",
    "downloadUrl",
    "output_url",
    "outputUrl",
    "resource_url",
    "resourceUrl",
    "image_url",
    "video_url",
    "audio_url",
}
_JOB_ID_KEYS = {"id", "job_id", "jobId", "job_set_id", "jobSetId"}


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass(frozen=True)
class HiggsfieldResult:
    raw: Any
    job_id: str | None
    urls: tuple[str, ...]


@dataclass(frozen=True)
class CreditBalance:
    credits: int | float | None
    warning: str | None = None


def _json_from_output(output: str) -> Any:
    stripped = output.strip()
    if not stripped:
        raise RunnerError("Higgsfield CLI returned an empty JSON response")
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        # 로그 프리앰블 뒤에 JSON 이 붙는 경우: **첫 최상위** 객체를 돌려준다.
        # 종전엔 모든 '{'/'[' 위치에서 디코드해 마지막(=가장 안쪽 중첩) 값을 골랐고,
        # 그러면 바깥 객체의 job id 가 사라져 유료 job 을 crash 후 재부착할 수 없었다
        # (2026-08-17 리뷰). 한 객체를 디코드하면 그 끝까지 건너뛰어 중첩 재스캔(O(n²))도 없앤다.
        decoder = json.JSONDecoder()
        index = 0
        length = len(stripped)
        while index < length:
            if stripped[index] not in "[{":
                index += 1
                continue
            try:
                value, _end = decoder.raw_decode(stripped, index)
            except json.JSONDecodeError:
                index += 1
                continue
            return value
    raise RunnerError("Higgsfield CLI returned malformed JSON")


def _walk(value: Any) -> Iterable[tuple[str | None, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield None, child
            yield from _walk(child)


def _extract_job_id(value: Any, fallback_text: str = "") -> str | None:
    for key, child in _walk(value):
        if key in _JOB_ID_KEYS and isinstance(child, str) and _UUID.fullmatch(child):
            return child
    match = re.search(
        rf"(?:job|generation)[^\n]{{0,80}}({_UUID.pattern})",
        fallback_text,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def _extract_urls(value: Any) -> tuple[str, ...]:
    urls: list[str] = []
    for key, child in _walk(value):
        is_url_key = key in _URL_KEYS or (
            isinstance(key, str) and key.lower().endswith("url")
        )
        if (
            is_url_key
            and isinstance(child, str)
            and child.startswith("https://")
            and child not in urls
        ):
            urls.append(child)
    return tuple(urls)


def _normalise_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def _enum(value: Any, allowed: set[str], label: str) -> str:
    normalised = str(value).lower()
    if normalised not in allowed:
        raise InvalidJobError(f"{label} must be one of {sorted(allowed)}")
    return normalised


def _integer(value: Any, allowed: set[int], label: str) -> str:
    if isinstance(value, bool):
        raise InvalidJobError(f"{label} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidJobError(f"{label} must be an integer") from exc
    if number not in allowed:
        raise InvalidJobError(f"{label} must be one of {sorted(allowed)}")
    return str(number)


class HiggsfieldCli:
    def __init__(
        self,
        config: RunnerConfig,
        *,
        run_func: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._run_func = run_func
        self._popen_factory = popen_factory
        self._sleep = sleeper
        self._monotonic = monotonic

    def _child_env(self) -> dict[str, str]:
        env = os.environ.copy()
        # The API service token must never be inherited by a third-party CLI.
        for name in (
            "CREATIVE_RUNNER_TOKEN",
            "CREATIVE_RUNNER_TOKEN_CURRENT",
            "CREATIVE_RUNNER_TOKEN_PREVIOUS",
        ):
            env.pop(name, None)
        return env

    def _quick(self, args: Sequence[str], *, timeout: float = 30.0) -> CommandResult:
        try:
            completed = self._run_func(
                list(args),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=self._child_env(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ConfigurationError(f"could not execute {args[0]}") from exc
        return CommandResult(
            tuple(args),
            completed.returncode,
            completed.stdout or "",
            completed.stderr or "",
        )

    def preflight(self) -> None:
        if (
            shutil.which(self.config.higgsfield_bin) is None
            and Path(self.config.higgsfield_bin).name == self.config.higgsfield_bin
        ):
            raise ConfigurationError("higgsfield CLI is not on PATH")

        version = self._quick([self.config.higgsfield_bin, "--version"], timeout=10)
        if version.returncode != 0:
            raise ConfigurationError("higgsfield --version failed")
        match = re.search(r"\bhiggsfield\s+(\d+\.\d+\.\d+)\b", version.stdout)
        if not match or match.group(1) != PINNED_HIGGSFIELD_VERSION:
            installed = match.group(1) if match else "unknown"
            raise ConfigurationError(
                f"higgsfield CLI must be {PINNED_HIGGSFIELD_VERSION}; installed version is {installed}"
            )

        account = self._quick(
            [self.config.higgsfield_bin, "account", "status", "--json", "--no-color"]
        )
        self._require_success(account, context="account preflight")

        workspace = self._quick(
            [self.config.higgsfield_bin, "workspace", "status", "--json", "--no-color"]
        )
        self._require_success(workspace, context="workspace preflight")
        try:
            workspace_payload = _json_from_output(workspace.stdout)
        except RunnerError as exc:
            raise ConfigurationError(
                "Higgsfield workspace status returned invalid JSON"
            ) from exc
        selected_workspace = any(
            isinstance(value, str) and value == self.config.workspace_id
            for _key, value in _walk(workspace_payload)
        )
        if not selected_workspace:
            raise HiggsfieldAuthRequired(
                "selected Higgsfield workspace does not match HIGGSFIELD_WORKSPACE_ID; run workspace set locally"
            )

    def credit_balance(self) -> CreditBalance:
        """Return only the numeric credit balance; never retain account identity/raw JSON."""
        try:
            result = self._quick(
                [
                    self.config.higgsfield_bin,
                    "account",
                    "status",
                    "--json",
                    "--no-color",
                ]
            )
        except RunnerError:
            return CreditBalance(None, "account_status_unavailable")
        if result.returncode != 0:
            combined = f"{result.stdout}\n{result.stderr}".lower()
            warning = (
                "account_authentication_required"
                if any(marker in combined for marker in _AUTH_MARKERS)
                else "account_status_unavailable"
            )
            return CreditBalance(None, warning)
        try:
            payload = _json_from_output(result.stdout)
        except RunnerError:
            return CreditBalance(None, "credits_response_invalid")
        value = payload.get("credits") if isinstance(payload, dict) else None
        if isinstance(value, bool):
            return CreditBalance(None, "credits_value_missing")
        try:
            credits = float(value)
        except (TypeError, ValueError):
            return CreditBalance(None, "credits_value_missing")
        if not math.isfinite(credits) or credits < 0:
            return CreditBalance(None, "credits_value_invalid")
        normalised: int | float = int(credits) if credits.is_integer() else credits
        return CreditBalance(normalised)

    def _require_success(self, result: CommandResult, *, context: str) -> None:
        if result.returncode == 0:
            return
        combined = f"{result.stdout}\n{result.stderr}".lower()
        if any(marker in combined for marker in _AUTH_MARKERS):
            raise HiggsfieldAuthRequired(
                f"Higgsfield {context} requires local authentication"
            )
        raise ConfigurationError(f"Higgsfield {context} failed")

    def _media_args(self, job_type: str, inputs: Sequence[LocalAsset]) -> list[str]:
        args: list[str] = []
        images = [asset for asset in inputs if asset.mime_type.startswith("image/")]
        videos = [asset for asset in inputs if asset.mime_type.startswith("video/")]

        if job_type in {"gpt_image_2", "marketing_studio_image"}:
            for asset in images:
                if asset.role in {"reference", "storyboard"}:
                    args.extend(["--image", str(asset.path)])
            return args

        if job_type == "marketing_studio_video":
            for asset in images:
                if asset.role in {"reference", "storyboard"}:
                    args.extend(["--image", str(asset.path)])
            return args

        if job_type == "reframe":
            if len(videos) != 1:
                raise InvalidJobError("reframe requires exactly one video input")
            args.extend(["--video", str(videos[0].path)])
            for asset in images:
                if asset.role in {"reference", "storyboard"}:
                    args.extend(["--image", str(asset.path)])
            return args

        if job_type == "brain_activity":
            if len(videos) != 1:
                raise InvalidJobError("brain_activity requires exactly one video input")
            return ["--video", str(videos[0].path)]
        raise InvalidJobError(f"unsupported job type: {job_type}")

    def build_command(
        self, attempt: ClaimedAttempt, inputs: Sequence[LocalAsset]
    ) -> list[str]:
        job_type = attempt.job_type
        if job_type not in _MODELS | _WORKFLOWS:
            raise InvalidJobError(f"job type is not allowlisted: {job_type}")

        params = {
            _normalise_key(str(key)): value for key, value in attempt.params.items()
        }
        internal_keys = {
            "output_preset",
            "overlay_box",
            "composite_source_ui",
            "source_ui_timeline",
        }
        cli_params = {
            key: value for key, value in params.items() if key not in internal_keys
        }
        expected_aspect = {
            ("gpt_image_2", "blog_hero_16_9"): "16:9",
            ("marketing_studio_image", "static_4_5"): "4:5",
            ("marketing_studio_image", "static_1_1"): "1:1",
            ("marketing_studio_video", "video_9_16"): "9:16",
            ("reframe", "video_9_16"): "9:16",
            ("reframe", "video_1_1"): "1:1",
            ("reframe", "video_16_9"): "16:9",
        }.get((job_type, attempt.brief_format))
        if (
            expected_aspect is not None
            and "aspect_ratio" in cli_params
            and str(cli_params["aspect_ratio"]).lower() != expected_aspect
        ):
            raise InvalidJobError(
                "aspect_ratio conflicts with the approved creative format"
            )

        args = [self.config.higgsfield_bin, "generate"]
        if job_type in _WORKFLOWS:
            args.extend(["workflow", job_type])
        else:
            args.extend(["create", job_type])

        if job_type in {
            "gpt_image_2",
            "marketing_studio_image",
            "marketing_studio_video",
        }:
            prompt = attempt.prompt.strip()
            if not prompt or len(prompt) > 8000 or "\x00" in prompt:
                raise InvalidJobError(
                    "generation prompt must contain 1-8000 safe characters"
                )
            args.extend(["--prompt", prompt])

        allowed_keys: set[str]
        if job_type == "gpt_image_2":
            allowed_keys = {"aspect_ratio", "resolution", "quality"}
            defaults: Mapping[str, Any] = {
                "aspect_ratio": "16:9",
                "resolution": "2k",
                "quality": "high",
            }
        elif job_type == "marketing_studio_image":
            allowed_keys = {"aspect_ratio", "resolution"}
            defaults = {
                "aspect_ratio": expected_aspect or "1:1",
                "resolution": "2k",
            }
        elif job_type == "marketing_studio_video":
            allowed_keys = {
                "aspect_ratio",
                "resolution",
                "duration",
                "mode",
                "specific_mode",
                "generate_audio",
            }
            defaults = {
                "aspect_ratio": "9:16",
                "resolution": "1080p",
                "duration": 15,
                "mode": "ugc",
                "specific_mode": "from_storyboard",
                "generate_audio": False,
            }
        elif job_type == "reframe":
            allowed_keys = {"aspect_ratio", "resolution", "mode"}
            defaults = {
                "aspect_ratio": expected_aspect or "9:16",
                "resolution": "1080p",
                "mode": "std",
            }
        else:
            allowed_keys = set()
            defaults = {}

        unknown = set(cli_params) - allowed_keys
        if unknown:
            raise InvalidJobError(
                f"job contains non-allowlisted parameters: {sorted(unknown)}"
            )
        values = {**defaults, **cli_params}

        if "aspect_ratio" in values:
            aspect = _enum(
                values["aspect_ratio"], {"16:9", "9:16", "4:5", "1:1"}, "aspect_ratio"
            )
            flag = "--aspect-ratio" if job_type == "reframe" else "--aspect_ratio"
            args.extend([flag, aspect])
        if "resolution" in values:
            allowed_resolutions = {
                "gpt_image_2": {"1k", "2k", "4k"},
                "marketing_studio_image": {"1k", "2k"},
                "marketing_studio_video": {"480p", "720p", "1080p"},
                "reframe": {"720p", "1080p"},
            }[job_type]
            args.extend(
                [
                    "--resolution",
                    _enum(values["resolution"], allowed_resolutions, "resolution"),
                ]
            )
        if "quality" in values:
            args.extend(
                [
                    "--quality",
                    _enum(values["quality"], {"low", "medium", "high"}, "quality"),
                ]
            )
        if "duration" in values:
            args.extend(["--duration", _integer(values["duration"], {15}, "duration")])
        if "mode" in values:
            modes = {"ugc"} if job_type == "marketing_studio_video" else {"std", "pro"}
            args.extend(["--mode", _enum(values["mode"], modes, "mode")])
        if "specific_mode" in values:
            args.extend(
                [
                    "--specific_mode",
                    _enum(
                        values["specific_mode"], {"from_storyboard"}, "specific_mode"
                    ),
                ]
            )
        if "generate_audio" in values:
            if values["generate_audio"] not in (False, "false", "False", 0):
                raise InvalidJobError(
                    "generate_audio must remain false; BidEasy uses approved founder audio"
                )
            args.extend(["--generate_audio", "false"])

        args.extend(self._media_args(job_type, inputs))
        args.extend(
            [
                "--wait",
                "--wait-timeout",
                self.config.wait_timeout,
                "--json",
                "--no-color",
            ]
        )
        return args

    def _run_long(
        self, args: Sequence[str], heartbeat: Callable[[], None]
    ) -> CommandResult:
        try:
            process = self._popen_factory(
                list(args),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=self._child_env(),
            )
        except OSError as exc:
            raise ConfigurationError("could not start Higgsfield CLI") from exc

        started = self._monotonic()
        while True:
            elapsed = self._monotonic() - started
            remaining = self.config.command_timeout_seconds - elapsed
            if remaining <= 0:
                process.kill()
                stdout, stderr = process.communicate()
                return CommandResult(
                    tuple(args),
                    process.returncode or -9,
                    stdout or "",
                    stderr or "",
                    timed_out=True,
                )
            try:
                stdout, stderr = process.communicate(
                    timeout=min(self.config.heartbeat_seconds, remaining)
                )
                return CommandResult(
                    tuple(args), process.returncode or 0, stdout or "", stderr or ""
                )
            except subprocess.TimeoutExpired:
                try:
                    heartbeat()
                except Exception:
                    process.kill()
                    process.communicate()
                    raise

    def _parse_result(self, result: CommandResult) -> HiggsfieldResult:
        raw = _json_from_output(result.stdout)
        return HiggsfieldResult(
            raw, _extract_job_id(raw, result.stdout), _extract_urls(raw)
        )

    def _recover(
        self, job_id: str, heartbeat: Callable[[], None]
    ) -> HiggsfieldResult | None:
        get_result = self._run_long(
            [
                self.config.higgsfield_bin,
                "generate",
                "get",
                job_id,
                "--json",
                "--no-color",
            ],
            heartbeat,
        )
        if get_result.returncode != 0:
            combined = f"{get_result.stdout}\n{get_result.stderr}".lower()
            if any(marker in combined for marker in _AUTH_MARKERS):
                raise HiggsfieldAuthRequired(
                    "Higgsfield authentication expired while recovering an existing job"
                )
            return None
        parsed = self._parse_result(get_result)
        status_values = {
            str(child).lower()
            for key, child in _walk(parsed.raw)
            if key in {"status", "state"} and isinstance(child, str)
        }
        if status_values & {"completed", "complete", "succeeded", "success", "done"}:
            return parsed
        if status_values & {"failed", "cancelled", "canceled"}:
            return None
        wait_result = self._run_long(
            [
                self.config.higgsfield_bin,
                "generate",
                "wait",
                job_id,
                "--timeout",
                "10m",
                "--interval",
                "5s",
                "--json",
                "--no-color",
            ],
            heartbeat,
        )
        if wait_result.returncode == 0:
            return self._parse_result(wait_result)
        combined = f"{wait_result.stdout}\n{wait_result.stderr}".lower()
        if any(marker in combined for marker in _AUTH_MARKERS):
            raise HiggsfieldAuthRequired(
                "Higgsfield authentication expired while waiting for an existing job"
            )
        return None

    def _sleep_with_heartbeat(
        self, seconds: float, heartbeat: Callable[[], None]
    ) -> None:
        remaining = seconds
        while remaining > 0:
            step = min(self.config.heartbeat_seconds, remaining)
            self._sleep(step)
            remaining -= step
            heartbeat()

    def run(
        self,
        attempt: ClaimedAttempt,
        inputs: Sequence[LocalAsset],
        heartbeat: Callable[[], None],
        *,
        on_job_id: Callable[[str], None] | None = None,
    ) -> HiggsfieldResult:
        # A reclaimed lease can carry a job submitted by the previous runner
        # process. Rejoin it before building or submitting anything new; if its
        # state cannot be proven, fail safely instead of risking another charge.
        if attempt.higgsfield_job_id:
            if on_job_id is not None:
                on_job_id(attempt.higgsfield_job_id)
            recovered = self._recover(attempt.higgsfield_job_id, heartbeat)
            if recovered is not None:
                return recovered
            raise HiggsfieldTimeout(
                "existing Higgsfield job could not be recovered; generation was not duplicated"
            )

        args = self.build_command(attempt, inputs)
        last_error = ""
        for retry_index in range(len(self.config.retry_backoffs) + 1):
            result = self._run_long(args, heartbeat)
            combined = f"{result.stdout}\n{result.stderr}"
            if result.returncode == 0 and not result.timed_out:
                parsed = self._parse_result(result)
                if parsed.job_id and on_job_id is not None:
                    on_job_id(parsed.job_id)
                return parsed

            try:
                partial = _json_from_output(result.stdout)
            except RunnerError:
                partial = {}
            job_id = _extract_job_id(partial, combined)
            if job_id:
                if on_job_id is not None:
                    on_job_id(job_id)
                recovered = self._recover(job_id, heartbeat)
                if recovered is not None:
                    return recovered

            lowered = combined.lower()
            if any(marker in lowered for marker in _AUTH_MARKERS):
                raise HiggsfieldAuthRequired(
                    "Higgsfield authentication expired; run auth login locally"
                )
            if result.timed_out or "timeout after" in lowered or "timed out" in lowered:
                raise HiggsfieldTimeout(
                    "Higgsfield timed out without a recoverable job id; generation was not duplicated"
                )

            is_5xx = bool(
                re.search(r"(?:http|status)(?:\s+code)?[=: ]+5\d\d\b", lowered)
            )
            transient = is_5xx or any(
                marker in lowered for marker in _RATE_LIMIT_MARKERS
            )
            if not transient:
                message = (result.stderr or result.stdout).strip().splitlines()
                safe_message = message[-1][:500] if message else "unknown CLI failure"
                raise RunnerError(f"Higgsfield generation failed: {safe_message}")

            last_error = "Higgsfield returned a transient 429/5xx error"
            if retry_index == len(self.config.retry_backoffs):
                break
            self._sleep_with_heartbeat(
                self.config.retry_backoffs[retry_index], heartbeat
            )

        raise RetryableHiggsfieldError(
            last_error or "Higgsfield transient retries exhausted"
        )
