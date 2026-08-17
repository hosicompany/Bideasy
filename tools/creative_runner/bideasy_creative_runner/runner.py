"""Lease-driven orchestration for one authenticated operator-Mac runner."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import tempfile
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .api import ClaimedAttempt, CreativeApiClient
from .assets import LocalAsset, SafeDownloader
from .brand_policy import BrandPolicy
from .config import PINNED_HIGGSFIELD_VERSION, RunnerConfig
from .copy_layers import CopySpec, validate_font_dir
from .errors import (
    ApiAuthenticationError,
    ApiError,
    AssetError,
    ConfigurationError,
    HiggsfieldAuthRequired,
    HiggsfieldTimeout,
    InvalidJobError,
    RetryableHiggsfieldError,
    RunnerError,
)
from .higgsfield import CreditBalance, HiggsfieldCli, HiggsfieldResult
from .postprocess import (
    CAMPAIGN_15S_TIMELINE,
    ProcessedAsset,
    find_role,
    process_image,
    process_video,
)

logger = logging.getLogger(__name__)


def _safe_error(exc: Exception) -> str:
    # Detailed subprocess/HTTP errors remain in the operator's local log. The
    # server receives only a bounded category so CLI credentials, signed URLs,
    # local paths, headers, and raw provider responses can never cross this API.
    if isinstance(exc, HiggsfieldAuthRequired):
        detail = "local Higgsfield authentication or workspace selection is required"
    elif isinstance(exc, HiggsfieldTimeout):
        detail = "Higgsfield job timed out or could not be safely rejoined; no duplicate was submitted"
    elif isinstance(exc, RetryableHiggsfieldError):
        detail = "Higgsfield 429/5xx retries were exhausted"
    elif isinstance(exc, InvalidJobError):
        detail = "claimed brief failed the local allowlist or brand-policy validation"
    elif isinstance(exc, AssetError):
        detail = "asset download, validation, or deterministic processing failed"
    elif isinstance(exc, ApiAuthenticationError):
        detail = "creative runner service authentication failed"
    elif isinstance(exc, ApiError):
        detail = "creative runner API request failed"
    elif isinstance(exc, ConfigurationError):
        detail = "local creative runner configuration failed validation"
    elif isinstance(exc, RunnerError):
        detail = "Higgsfield runner operation failed"
    else:
        detail = "unexpected local runner failure"
    return f"{type(exc).__name__}: {detail}"[:1000]


def _normalise_metric_key(value: str) -> str:
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    return re.sub(r"[^a-z0-9]+", "_", snake.lower()).strip("_")


def _walk_named_values(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield _normalise_metric_key(str(key)), child
            yield from _walk_named_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_named_values(child)


def _metric_scalar(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("value", "score", "seconds", "second"):
            if key in value and not isinstance(value[key], (dict, list)):
                return value[key]
        return None
    return value if not isinstance(value, list) else None


def _unique_metric(raw: Any, aliases: set[str]) -> Any:
    values: list[Any] = []
    for key, value in _walk_named_values(raw):
        if key not in aliases:
            continue
        scalar = _metric_scalar(value)
        if scalar is not None and not any(
            type(existing) is type(scalar) and existing == scalar for existing in values
        ):
            values.append(scalar)
    return values[0] if len(values) == 1 else None


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalise_virality(raw: Any) -> dict[str, Any]:
    hook = _finite_number(
        _unique_metric(
            raw,
            {
                "hook_peak_seconds",
                "hook_peak_second",
                "peak_hook_seconds",
                "peak_hook_second",
                "hook_peak_time_seconds",
            },
        )
    )
    if hook is not None and hook < 0:
        hook = None

    sustain = _finite_number(
        _unique_metric(
            raw,
            {
                "sustain_score",
                "sustained_attention_score",
                "attention_sustain_score",
            },
        )
    )
    if sustain is not None and 1 < sustain <= 100:
        sustain /= 100
    if sustain is not None and not 0 <= sustain <= 1:
        sustain = None

    attention = _unique_metric(
        raw,
        {
            "attention_overlaps_product",
            "product_attention_overlap",
            "attention_overlaps_product_scene",
        },
    )
    if not isinstance(attention, bool):
        attention = None

    report_url = _unique_metric(
        raw,
        {"report_url", "open_report_url", "virality_report_url"},
    )
    if isinstance(report_url, str):
        try:
            parsed = urlsplit(report_url)
            port = parsed.port
        except ValueError:
            parsed = None
            port = None
        if parsed is not None:
            hostname = (parsed.hostname or "").lower().rstrip(".")
        else:
            hostname = ""
        if (
            parsed is None
            or parsed.scheme != "https"
            or not hostname
            or not (hostname == "higgsfield.ai" or hostname.endswith(".higgsfield.ai"))
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
            or parsed.query
            or parsed.fragment
        ):
            report_url = None
        else:
            # Rebuild from parsed components so control characters or alternate
            # URL spellings never cross the public output boundary.
            report_url = urlunsplit(("https", parsed.netloc, parsed.path, "", ""))
    else:
        report_url = None
    return {
        "hook_peak_seconds": hook,
        "sustain_score": sustain,
        "attention_overlaps_product": attention,
        "report_url": report_url,
    }


def _credit_usage(before: CreditBalance, after: CreditBalance) -> dict[str, Any]:
    warnings = [
        warning
        for warning in (before.warning, after.warning)
        if isinstance(warning, str) and warning
    ]
    delta: int | float | None = None
    if before.credits is not None and after.credits is not None:
        measured = float(before.credits) - float(after.credits)
        delta = int(measured) if measured.is_integer() else round(measured, 6)
        if measured < 0:
            warnings.append("credits_increased_during_attempt")
    return {
        "before": before.credits,
        "after": after.credits,
        "delta": delta,
        "warnings": list(dict.fromkeys(warnings)),
    }


def _write_report(
    result: HiggsfieldResult | None,
    directory: Path,
    *,
    warning: str | None = None,
    generation_job_id: str | None = None,
) -> Path:
    """Virality 보고서를 쓴다.

    ``result`` 는 **Predictor** 작업이다. 생성 job 은 별개의 외부 작업이라 호출부가
    ``generation_job_id`` 로 넘겨야 한다 — 종전엔 두 칸에 Predictor id 를 똑같이 써서
    서버가 attempt 기록과 대조하면 생성 job 이 틀린 값으로 남았다(2026-08-17 리뷰).
    생성과 분석이 한 작업인 경우(brain_activity)만 같은 id 를 넘긴다.
    """
    report = directory / "virality-report.json"
    raw = result.raw if result is not None else None
    metrics = _normalise_virality(raw)
    if warning is None and any(
        metrics[key] is None
        for key in (
            "hook_peak_seconds",
            "sustain_score",
            "attention_overlaps_product",
        )
    ):
        warning = "virality_metrics_incomplete"
    payload = {
        "higgsfield_job_id": generation_job_id if generation_job_id is not None else (result.job_id if result is not None else None),
        "virality_job_id": result.job_id if result is not None else None,
        **metrics,
        "human_review_required": True,
        "analysis_warning": warning,
    }
    report.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def _attach_credit_usage(report: Path, usage: dict[str, Any]) -> None:
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AssetError("local virality report could not be updated") from exc
    if not isinstance(payload, dict):
        raise AssetError("local virality report must be a JSON object")
    payload["credit_usage"] = usage
    report.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


class CreativeRunner:
    def __init__(
        self,
        config: RunnerConfig,
        *,
        api: CreativeApiClient | None = None,
        higgsfield: HiggsfieldCli | None = None,
        downloader_factory: Callable[..., SafeDownloader] = SafeDownloader,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.api = api or CreativeApiClient(config)
        self._owns_api = api is None
        self.higgsfield = higgsfield or HiggsfieldCli(config)
        self._downloader_factory = downloader_factory
        self._sleep = sleeper
        self.brand_policy = BrandPolicy.load(config.brand_policy_path)

    def close(self) -> None:
        if self._owns_api:
            self.api.close()

    def preflight(self) -> None:
        self.brand_policy = BrandPolicy.load(self.config.brand_policy_path)
        self.brand_policy.verify_local_assets(self.config.brand_asset_root)
        validate_font_dir(self.config.font_dir)
        self.higgsfield.preflight()

    def _copy_spec(self, attempt: ClaimedAttempt) -> CopySpec:
        return CopySpec(
            hook=attempt.hook,
            body=attempt.body_copy,
            cta=attempt.cta_copy,
            endline=self.brand_policy.endline,
            non_prediction_line=self.brand_policy.video_non_prediction_line,
            disclaimer=self.brand_policy.disclaimer,
            colors=self.brand_policy.colors,
        )

    def _heartbeat(
        self,
        attempt: ClaimedAttempt,
        status: str,
        job_id: str | None = None,
        virality_job_id: str | None = None,
    ) -> None:
        self.api.heartbeat(
            attempt.attempt_id,
            status=status,
            higgsfield_job_id=job_id,
            virality_job_id=virality_job_id,
        )

    def _wait_with_processing_heartbeats(
        self,
        attempt: ClaimedAttempt,
        job_id: str | None,
        seconds: float,
    ) -> None:
        remaining = seconds
        while remaining > 0:
            step = min(self.config.heartbeat_seconds, remaining)
            self._sleep(step)
            remaining -= step
            self._heartbeat(attempt, "PROCESSING", job_id)

    def _download_inputs(
        self, attempt: ClaimedAttempt, directory: Path
    ) -> tuple[list[LocalAsset], SafeDownloader]:
        downloader = self._downloader_factory(
            max_bytes=self.config.max_asset_bytes,
            input_hosts=self.config.input_hosts,
            heartbeat=lambda: self._heartbeat(attempt, "GENERATING"),
            service_token=self.config.service_token,
            authenticated_input_origin=self.config.api_base,
            authenticated_input_prefix=self.config.api_prefix,
        )
        try:
            inputs = [
                downloader.input_asset(asset, directory, index)
                for index, asset in enumerate(attempt.input_assets, start=1)
            ]
        except Exception:
            downloader.close()
            raise
        return inputs, downloader

    def _download_result(
        self,
        attempt: ClaimedAttempt,
        result: HiggsfieldResult,
        directory: Path,
        downloader: SafeDownloader,
    ) -> LocalAsset:
        expected_prefix = (
            "video/"
            if attempt.job_type in {"marketing_studio_video", "reframe"}
            else "image/"
        )
        failures: list[str] = []
        for index, url in enumerate(result.urls, start=1):
            try:
                return downloader.generated_asset(
                    url,
                    directory,
                    index,
                    expected_prefix=expected_prefix,
                )
            except AssetError as exc:
                failures.append(str(exc))
        detail = (
            failures[-1] if failures else "CLI JSON contained no generated media URL"
        )
        raise AssetError(f"could not download Higgsfield result: {detail}")

    def _postprocess(
        self,
        attempt: ClaimedAttempt,
        generated: LocalAsset,
        inputs: list[LocalAsset],
        directory: Path,
    ) -> list[ProcessedAsset]:
        params = dict(attempt.params)
        # The acquisition timeline is a runner-owned, versioned contract. A
        # brief cannot alter it, and Reframe keeps the duration/timing of its
        # already-composited source.
        if attempt.job_type == "marketing_studio_video":
            params["source_ui_timeline"] = CAMPAIGN_15S_TIMELINE
        else:
            params.pop("source_ui_timeline", None)
        if attempt.brief_format:
            params["output_preset"] = attempt.brief_format
        copy_spec = (
            self._copy_spec(attempt)
            if attempt.job_type in {"marketing_studio_image", "marketing_studio_video"}
            else None
        )
        if generated.mime_type.startswith("image/"):
            source_ui = find_role(inputs, "source_ui", "image/")
            return process_image(
                generated.path,
                directory,
                params,
                copy_spec=copy_spec,
                font_dir=self.config.font_dir if copy_spec is not None else None,
                source_ui=source_ui,
            )
        if generated.mime_type.startswith("video/"):
            voiceover = find_role(inputs, "voiceover", "audio/")
            source_ui_video = find_role(inputs, "source_ui", "video/")
            source_ui_image = find_role(inputs, "source_ui", "image/")
            if source_ui_video and source_ui_image:
                raise AssetError("only one source_ui media input can be composited")
            source_ui = source_ui_video or source_ui_image
            if (
                attempt.job_type != "marketing_studio_video"
                or params.get("composite_source_ui") is not True
            ):
                source_ui = None
            return process_video(
                generated.path,
                directory,
                params,
                copy_spec=copy_spec,
                font_dir=self.config.font_dir if copy_spec is not None else None,
                voiceover=voiceover,
                source_ui=source_ui,
                ffmpeg_bin=self.config.ffmpeg_bin,
                ffprobe_bin=self.config.ffprobe_bin,
                heartbeat=lambda: self._heartbeat(attempt, "PROCESSING"),
            )
        raise AssetError(f"unsupported generated MIME: {generated.mime_type}")

    def _automatic_virality_report(
        self,
        attempt: ClaimedAttempt,
        processed: list[ProcessedAsset],
        directory: Path,
        generation_job_id: str | None,
    ) -> ProcessedAsset:
        primary_videos = [
            asset for asset in processed if asset.kind == "mp4" and asset.is_primary
        ]
        if len(primary_videos) != 1:
            raise AssetError(
                "automatic Virality Predictor requires exactly one final primary MP4"
            )
        final_video = primary_videos[0].path
        analysis_attempt = replace(
            attempt,
            job_type="brain_activity",
            prompt="",
            params={},
            input_assets=(),
            higgsfield_job_id=attempt.virality_job_id,
        )
        local_video = LocalAsset(
            final_video,
            "video/mp4",
            "reference",
            _sha256_file(final_video),
        )
        try:
            result = self.higgsfield.run(
                analysis_attempt,
                [local_video],
                lambda: self._heartbeat(attempt, "PROCESSING", generation_job_id),
                on_job_id=lambda predictor_id: self._heartbeat(
                    attempt,
                    "PROCESSING",
                    generation_job_id,
                    predictor_id,
                ),
            )
            report = _write_report(result, directory, generation_job_id=generation_job_id)
            metadata = {"virality_job_id": result.job_id, "analysis_warning": None}
        except ApiError:
            raise
        except RunnerError as exc:
            warning = f"virality_unavailable_{type(exc).__name__}"
            logger.warning(
                "creative attempt %s Virality Predictor unavailable: %s",
                attempt.attempt_id,
                type(exc).__name__,
            )
            report = _write_report(None, directory, warning=warning, generation_job_id=generation_job_id)
            metadata = {"virality_job_id": None, "analysis_warning": warning}
        return ProcessedAsset(
            report,
            "virality_report",
            False,
            metadata,
        )

    def _upload_assets(
        self,
        attempt: ClaimedAttempt,
        generated: LocalAsset,
        processed: list[ProcessedAsset],
        job_id: str | None,
        credit_usage: dict[str, Any],
    ) -> None:
        common: dict[str, Any] = {
            "higgsfield_job_id": job_id,
            "cli_version": PINNED_HIGGSFIELD_VERSION,
            "credit_usage": credit_usage,
            # The backend persists metadata.review as CreativeOutput.review_json.
            # Keep the numeric-only accounting there for original and final assets.
            "review": {
                "higgsfield_job_id": job_id,
                "cli_version": PINNED_HIGGSFIELD_VERSION,
                "credit_usage": credit_usage,
            },
        }

        def retry_waiter(seconds: float) -> None:
            self._wait_with_processing_heartbeats(attempt, job_id, seconds)

        self._heartbeat(attempt, "PROCESSING", job_id)
        self.api.upload_output(
            attempt.attempt_id,
            generated.path,
            kind="original",
            is_primary=False,
            metadata={**common, "mime_type": generated.mime_type},
            retry_waiter=retry_waiter,
        )
        # The backend transitions to REVIEW_REQUIRED on primary upload. Auxiliary
        # derivatives must therefore be uploaded first and the representative last.
        for asset in sorted(processed, key=lambda item: item.is_primary):
            self._heartbeat(attempt, "PROCESSING", job_id)
            metadata = {**common, **asset.metadata}
            asset_review = asset.metadata.get("review")
            metadata["review"] = {
                **common["review"],
                **(asset_review if isinstance(asset_review, dict) else {}),
            }
            self.api.upload_output(
                attempt.attempt_id,
                asset.path,
                kind=asset.kind,
                is_primary=asset.is_primary,
                metadata=metadata,
                retry_waiter=retry_waiter,
            )

    def execute(self, attempt: ClaimedAttempt) -> None:
        # Reload for every brief so an operator-reviewed policy update takes effect
        # without restarting a long-running local process.
        self.brand_policy = BrandPolicy.load(self.config.brand_policy_path)
        self.brand_policy.validate_attempt(attempt)
        with tempfile.TemporaryDirectory(
            prefix=f"bideasy-creative-{attempt.attempt_id}-"
        ) as raw_directory:
            directory = Path(raw_directory)
            inputs, downloader = self._download_inputs(attempt, directory)
            credits_before = self.higgsfield.credit_balance()
            credits_after: CreditBalance | None = None
            try:
                self._heartbeat(attempt, "GENERATING")
                result = self.higgsfield.run(
                    attempt,
                    inputs,
                    lambda: self._heartbeat(
                        attempt,
                        "GENERATING",
                        attempt.higgsfield_job_id,
                    ),
                    on_job_id=lambda generation_id: self._heartbeat(
                        attempt,
                        "GENERATING",
                        generation_id,
                    ),
                )
                self._heartbeat(attempt, "PROCESSING", result.job_id)
                downloader.set_heartbeat(
                    lambda: self._heartbeat(attempt, "PROCESSING", result.job_id)
                )

                if attempt.job_type == "brain_activity":
                    # 생성·분석이 한 작업이라 두 id 가 같은 것이 정확하다
                    report = _write_report(result, directory, generation_job_id=result.job_id)
                    credits_after = self.higgsfield.credit_balance()
                    usage = _credit_usage(credits_before, credits_after)
                    _attach_credit_usage(report, usage)
                    self.api.upload_output(
                        attempt.attempt_id,
                        report,
                        kind="virality_report",
                        is_primary=False,
                        metadata={
                            "higgsfield_job_id": result.job_id,
                            "cli_version": PINNED_HIGGSFIELD_VERSION,
                            "credit_usage": usage,
                        },
                        retry_waiter=lambda seconds: (
                            self._wait_with_processing_heartbeats(
                                attempt, result.job_id, seconds
                            )
                        ),
                    )
                    return

                generated = self._download_result(
                    attempt, result, directory, downloader
                )
                processed = self._postprocess(attempt, generated, inputs, directory)
                if attempt.job_type in {"marketing_studio_video", "reframe"}:
                    processed.append(
                        self._automatic_virality_report(
                            attempt,
                            processed,
                            directory,
                            result.job_id,
                        )
                    )
                credits_after = self.higgsfield.credit_balance()
                usage = _credit_usage(credits_before, credits_after)
                for asset in processed:
                    if asset.kind == "virality_report":
                        _attach_credit_usage(asset.path, usage)
                self._upload_assets(
                    attempt,
                    generated,
                    processed,
                    result.job_id,
                    usage,
                )
            except Exception:
                if credits_after is None:
                    credits_after = self.higgsfield.credit_balance()
                usage = _credit_usage(credits_before, credits_after)
                logger.warning(
                    "creative attempt %s stopped with credit usage before=%s after=%s delta=%s warnings=%s",
                    attempt.attempt_id,
                    usage["before"],
                    usage["after"],
                    usage["delta"],
                    usage["warnings"],
                )
                raise
            finally:
                downloader.close()

    def run_once(self) -> bool:
        attempt = self.api.claim()
        if attempt is None:
            return False
        try:
            self.execute(attempt)
        except Exception as exc:
            logger.exception("creative attempt %s failed", attempt.attempt_id)
            auth_required = bool(getattr(exc, "auth_required", False))
            retryable = bool(getattr(exc, "retryable", False))
            try:
                self.api.fail(
                    attempt.attempt_id,
                    _safe_error(exc),
                    auth_required=auth_required,
                    retryable=retryable,
                )
            except ApiError:
                logger.exception("could not report creative attempt failure")
            if auth_required:
                raise
        return True

    def run_forever(self) -> None:
        self.preflight()
        while True:
            worked = self.run_once()
            if not worked:
                self._sleep(self.config.poll_seconds)
