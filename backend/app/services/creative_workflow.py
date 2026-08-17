"""Creative brief state machine, runner leases, and verified asset storage."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from fastapi import UploadFile
from pydantic import ValidationError
from sqlalchemy import and_, case, func, or_, text
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.db import models
from app.schemas.creative import CreativeBriefCreate, CreativeBriefUpdate, GenerationSpec
from app.services import creative_input_assets


BRIEF_STATUSES = {
    "DRAFT",
    "BRIEF_APPROVED",
    "QUEUED",
    "CLAIMED",
    "GENERATING",
    "PROCESSING",
    "REVIEW_REQUIRED",
    "APPROVED",
    "PUBLISHED",
    "AUTH_REQUIRED",
    "CHANGES_REQUESTED",
    "STALE",
    "FAILED",
}
ACTIVE_ATTEMPT_STATUSES = {"CLAIMED", "GENERATING", "PROCESSING"}
RUNNER_OUTPUT_STATUSES = ACTIVE_ATTEMPT_STATUSES | {"REVIEW_REQUIRED"}
FINAL_PRIMARY_KINDS = {"final_png", "webp", "mp4"}
OUTPUT_KINDS = {
    "original",
    "final_png",
    "webp",
    "mp4",
    "poster",
    "thumbnail",
    "virality_report",
}

_MIME_EXTENSIONS: dict[str, tuple[str, set[str]]] = {
    "image/png": (".png", {".png"}),
    "image/jpeg": (".jpg", {".jpg", ".jpeg"}),
    "image/webp": (".webp", {".webp"}),
    "video/mp4": (".mp4", {".mp4"}),
    "application/json": (".json", {".json"}),
}
_KIND_MIMES: dict[str, set[str]] = {
    "original": {"image/png", "image/jpeg", "image/webp", "video/mp4"},
    "final_png": {"image/png"},
    "webp": {"image/webp"},
    "mp4": {"video/mp4"},
    "poster": {"image/png", "image/jpeg", "image/webp"},
    "thumbnail": {"image/png", "image/jpeg", "image/webp"},
    "virality_report": {"application/json"},
}
_EXPECTED_DIMENSIONS: dict[str, tuple[int, int]] = {
    "blog_hero_16_9": (1376, 768),
    "static_4_5": (1080, 1350),
    "static_1_1": (1080, 1080),
    "video_9_16": (1080, 1920),
    "video_1_1": (1080, 1080),
    "video_16_9": (1280, 720),
}

_VIRALITY_REPORT_KEYS = {
    "higgsfield_job_id",
    "virality_job_id",
    "hook_peak_seconds",
    "sustain_score",
    "attention_overlaps_product",
    "report_url",
    "human_review_required",
    "analysis_warning",
    "credit_usage",
}
_CREDIT_USAGE_KEYS = {"before", "after", "delta", "warnings"}
_SAFE_REPORT_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


class CreativeWorkflowError(Exception):
    """Base workflow error suitable for an API 4xx response."""


class CreativeNotFound(CreativeWorkflowError):
    pass


class CreativeConflict(CreativeWorkflowError):
    pass


class CreativeValidationError(CreativeWorkflowError):
    pass


def utcnow() -> datetime:
    """The project stores UTC in timezone-naive SQL DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _report_number(
    value: Any,
    *,
    field: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CreativeValidationError(f"Virality {field} 값의 형식이 올바르지 않아요")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise CreativeValidationError(f"Virality {field} 값은 유한한 숫자여야 해요")
    if minimum is not None and numeric < minimum:
        raise CreativeValidationError(f"Virality {field} 값이 허용 범위를 벗어났어요")
    if maximum is not None and numeric > maximum:
        raise CreativeValidationError(f"Virality {field} 값이 허용 범위를 벗어났어요")
    return value


def _report_identifier(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _SAFE_REPORT_IDENTIFIER.fullmatch(value):
        raise CreativeValidationError(f"Virality {field} 값의 형식이 올바르지 않아요")
    return value


def _safe_higgsfield_report_url(value: Any) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) > 2048
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or re.search(r"%0[0-9a-f]|%7f", value, re.IGNORECASE)
    ):
        raise CreativeValidationError("Virality report_url 형식이 올바르지 않아요")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise CreativeValidationError("Virality report_url 형식이 올바르지 않아요") from exc
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme.lower() != "https"
        or not (hostname == "higgsfield.ai" or hostname.endswith(".higgsfield.ai"))
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise CreativeValidationError("Virality report_url은 안전한 Higgsfield URL이어야 해요")
    return urlunsplit(("https", hostname, parsed.path, "", ""))


def _validate_credit_usage(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _CREDIT_USAGE_KEYS:
        raise CreativeValidationError("Virality credit_usage 스키마가 올바르지 않아요")
    warnings = value["warnings"]
    if not isinstance(warnings, list) or len(warnings) > 32:
        raise CreativeValidationError("Virality credit_usage warnings 형식이 올바르지 않아요")
    safe_warnings: list[str] = []
    for warning in warnings:
        safe_warning = _report_identifier(warning, field="credit_usage warning")
        if safe_warning is None:
            raise CreativeValidationError(
                "Virality credit_usage warning 값의 형식이 올바르지 않아요"
            )
        if safe_warning not in safe_warnings:
            safe_warnings.append(safe_warning)
    return {
        "before": _report_number(value["before"], field="credit before", minimum=0),
        "after": _report_number(value["after"], field="credit after", minimum=0),
        "delta": _report_number(value["delta"], field="credit delta"),
        "warnings": safe_warnings,
    }


def _validate_virality_report(
    report: dict[str, Any],
    *,
    expected_generation_job_id: str | None = None,
    expected_predictor_job_id: str | None = None,
) -> dict[str, Any]:
    """Virality 보고서를 검증한다.

    생성 job(higgsfield_job_id)과 Predictor job(virality_job_id)은 **서로 다른 외부 작업**이다
    (마이그 f1c7a4e82d90 이 그래서 별도 컬럼을 두었다). 불변식은 두 값이 같다는 게 아니라
    **이 attempt 에 기록된 각 job 과 일치한다** 는 것이다 — 다른 attempt 의 보고서가 섞이는
    것을 막되, 정상 보고서를 버리면 안 된다(2026-08-17 리뷰).
    """
    unknown_keys = set(report) - _VIRALITY_REPORT_KEYS
    if unknown_keys:
        raise CreativeValidationError("Virality 보고서에 허용되지 않은 필드가 있어요")

    normalized = dict(report)
    for field in ("higgsfield_job_id", "virality_job_id", "analysis_warning"):
        if field in normalized:
            normalized[field] = _report_identifier(normalized[field], field=field)
    generation_job_id = normalized.get("higgsfield_job_id")
    predictor_job_id = normalized.get("virality_job_id")
    if expected_generation_job_id and generation_job_id and generation_job_id != expected_generation_job_id:
        raise CreativeValidationError("Virality 보고서의 생성 job ID가 이 attempt 의 기록과 달라요")
    if expected_predictor_job_id and predictor_job_id and predictor_job_id != expected_predictor_job_id:
        raise CreativeValidationError("Virality 보고서의 Predictor job ID가 이 attempt 의 기록과 달라요")

    if "hook_peak_seconds" in normalized:
        normalized["hook_peak_seconds"] = _report_number(
            normalized["hook_peak_seconds"],
            field="hook_peak_seconds",
            minimum=0,
        )
    if "sustain_score" in normalized:
        normalized["sustain_score"] = _report_number(
            normalized["sustain_score"],
            field="sustain_score",
            minimum=0,
            maximum=100,
        )
    if "attention_overlaps_product" in normalized:
        attention = normalized["attention_overlaps_product"]
        if attention is not None and not isinstance(attention, bool):
            raise CreativeValidationError(
                "Virality attention_overlaps_product 값은 boolean이어야 해요"
            )
    if "report_url" in normalized:
        normalized["report_url"] = _safe_higgsfield_report_url(normalized["report_url"])
    # 키를 빼면 통과하던 구멍 — 명시적으로 True 여야 한다(누락도 거부).
    if normalized.get("human_review_required") is not True:
        raise CreativeValidationError("Virality 보고서는 사람 검수가 필요하다고 표시해야 해요")
    if "credit_usage" in normalized:
        normalized["credit_usage"] = _validate_credit_usage(normalized["credit_usage"])
    return normalized


def get_brief(db: Session, creative_id: str) -> models.CreativeBrief:
    brief = (
        db.query(models.CreativeBrief)
        .options(
            selectinload(models.CreativeBrief.attempts).selectinload(
                models.CreativeAttempt.outputs
            )
        )
        .filter(models.CreativeBrief.id == creative_id)
        .first()
    )
    if brief is None:
        raise CreativeNotFound("크리에이티브를 찾을 수 없어요")
    return brief


def list_briefs(
    db: Session,
    *,
    status: str | None = None,
    source_type: str | None = None,
    limit: int = 100,
) -> list[models.CreativeBrief]:
    query = db.query(models.CreativeBrief).options(
        selectinload(models.CreativeBrief.attempts).selectinload(models.CreativeAttempt.outputs)
    )
    if status:
        if status not in BRIEF_STATUSES:
            raise CreativeValidationError("알 수 없는 크리에이티브 상태예요")
        query = query.filter(models.CreativeBrief.status == status)
    if source_type:
        query = query.filter(models.CreativeBrief.source_type == source_type)
    return query.order_by(models.CreativeBrief.updated_at.desc()).limit(max(1, min(limit, 200))).all()


def create_brief(db: Session, payload: CreativeBriefCreate) -> models.CreativeBrief:
    brief = models.CreativeBrief(
        id=str(uuid.uuid4()),
        status="DRAFT",
        **payload.model_dump(),
    )
    db.add(brief)
    db.commit()
    return get_brief(db, brief.id)


def blog_source_hash(post: models.BlogPost) -> str:
    return _canonical_hash(
        {
            "id": post.id,
            "slug": post.slug,
            "title": post.title,
            "summary": post.summary,
            "category": post.category,
            "tags": post.tags,
            "cover": post.cover,
            "hero": post.hero,
            "body_md": post.body_md,
            "blocks_json": post.blocks_json,
        }
    )


def mark_source_creatives_stale(
    db: Session,
    *,
    source_type: str,
    source_ref_id: str,
    current_hash: str | None = None,
) -> int:
    query = (
        db.query(models.CreativeBrief)
        .options(selectinload(models.CreativeBrief.attempts))
        .filter(
            models.CreativeBrief.source_type == source_type,
            models.CreativeBrief.source_ref_id == source_ref_id,
            models.CreativeBrief.status != "STALE",
        )
    )
    if current_hash is not None:
        query = query.filter(
            or_(
                models.CreativeBrief.source_hash.is_(None),
                models.CreativeBrief.source_hash != current_hash,
            )
        )
    stale_briefs = query.all()
    for brief in stale_briefs:
        # approved_by/approved_at 은 지우지 않는다 — '한 번 승인됨' 은 역사적 사실이고
        # growth._known_creative 가 그 컬럼으로 귀속 유지 여부를 판정한다. 재사용 차단은
        # status="STALE" 만으로 충분하다(승인·큐·게시 전이가 전부 status 를 본다).
        brief.status = "STALE"
        for attempt in brief.attempts:
            attempt.status = "STALE"
            attempt.lease_expires_at = None
    if stale_briefs:
        db.commit()
    return len(stale_briefs)


def create_brief_from_blog(db: Session, post_id: int) -> models.CreativeBrief:
    post = db.query(models.BlogPost).filter(models.BlogPost.id == post_id).first()
    if post is None:
        raise CreativeNotFound("블로그 글을 찾을 수 없어요")
    source_hash = blog_source_hash(post)
    mark_source_creatives_stale(
        db,
        source_type="blog",
        source_ref_id=str(post.id),
        current_hash=source_hash,
    )
    existing = (
        db.query(models.CreativeBrief)
        .filter(
            models.CreativeBrief.source_type == "blog",
            models.CreativeBrief.source_ref_id == str(post.id),
            models.CreativeBrief.source_hash == source_hash,
        )
        .order_by(models.CreativeBrief.created_at.desc())
        .first()
    )
    if existing is not None:
        return get_brief(db, existing.id)

    blocks = post.blocks_json or {}
    hero_prompt = next(
        (
            str(item.get("prompt", "")).strip()
            for item in (blocks.get("image_prompts") or [])
            if item.get("slot") == "hero" and item.get("prompt")
        ),
        "",
    )
    if not hero_prompt:
        hero_prompt = (
            "Editorial visual for a Korean public-procurement guide, clean flat composition, "
            "deep blue #3182F6 and light gray #F2F4F6, calm trustworthy mood, no logo, "
            "no watermark, no letters, no numbers, no interface reconstruction. "
            f"Theme: {post.title}"
        )
    payload = CreativeBriefCreate(
        source_type="blog",
        source_ref_id=str(post.id),
        source_hash=source_hash,
        campaign_key=f"blog_{post.slug}"[:120],
        concept_key="blog_hero",
        variant="A",
        channel="blog",
        format="blog_hero_16_9",
        hook=post.title,
        body_copy=post.summary or "",
        cta_copy="이 공고 확인하기",
        landing_path=f"/blog/{post.slug}",
        utm_source="naver_blog",
        utm_medium="organic",
        utm_campaign=f"creative_blog_{post.slug}"[:160],
        generation_spec_json={
            "job_type": "gpt_image_2",
            "prompt": hero_prompt,
            "params": {"aspect_ratio": "16:9", "resolution": "2K", "quality": "high"},
            "input_files": [],
        },
    )
    return create_brief(db, payload)


def update_brief(
    db: Session,
    creative_id: str,
    payload: CreativeBriefUpdate,
) -> models.CreativeBrief:
    brief = get_brief(db, creative_id)
    data = payload.model_dump(exclude_unset=True)
    required = {
        "source_type",
        "campaign_key",
        "concept_key",
        "variant",
        "channel",
        "format",
        "hook",
        "body_copy",
        "cta_copy",
        "landing_path",
        "generation_spec_json",
    }
    if any(key in data and data[key] is None for key in required):
        raise CreativeValidationError("필수 brief 필드는 null로 비울 수 없어요")

    changed = False
    for key, value in data.items():
        if getattr(brief, key) != value:
            setattr(brief, key, value)
            changed = True
    if not changed:
        return brief

    brief.version += 1
    brief.approved_by = None
    brief.approved_at = None
    if brief.status in {"DRAFT", "CHANGES_REQUESTED"}:
        pass
    elif brief.status == "BRIEF_APPROVED":
        brief.status = "DRAFT"
    else:
        brief.status = "STALE"
    for attempt in brief.attempts:
        attempt.status = "STALE"
        attempt.lease_expires_at = None
    db.commit()
    return get_brief(db, creative_id)


def validate_generation_spec(
    brief: models.CreativeBrief,
    db: Session,
) -> GenerationSpec:
    try:
        spec = GenerationSpec.model_validate(brief.generation_spec_json or {})
    except ValidationError as exc:
        raise CreativeValidationError(f"생성 설정을 확인해 주세요: {exc.errors()[0]['msg']}") from exc
    allowed_formats = {
        "gpt_image_2": {"blog_hero_16_9"},
        "marketing_studio_image": {"static_4_5", "static_1_1"},
        "marketing_studio_video": {"video_9_16"},
        "reframe": {"video_9_16", "video_1_1", "video_16_9"},
        "brain_activity": {"video_9_16", "video_1_1", "video_16_9"},
    }
    if brief.format not in allowed_formats[spec.job_type]:
        allowed = ", ".join(sorted(allowed_formats[spec.job_type]))
        raise CreativeValidationError(
            f"{spec.job_type} 작업의 출력 형식은 {allowed} 중 하나여야 해요"
        )
    if spec.job_type in {"gpt_image_2", "marketing_studio_image", "marketing_studio_video"}:
        if not spec.prompt.strip():
            raise CreativeValidationError("이 작업은 빈 prompt로 큐에 넣을 수 없어요")
    if spec.job_type == "gpt_image_2" and spec.input_files:
        raise CreativeValidationError("블로그 hero 배경 생성에는 입력 파일을 사용할 수 없어요")
    if spec.job_type == "marketing_studio_image":
        source_ui_inputs = [
            item
            for item in spec.input_files
            if item.role == "source_ui" and item.mime_type.startswith("image/")
        ]
        if len(spec.input_files) != 1 or len(source_ui_inputs) != 1:
            raise CreativeValidationError(
                "Marketing Studio 이미지에는 실제 제품 화면 source_ui 이미지가 정확히 하나 필요해요"
            )
        if spec.params.get("composite_source_ui") is not True:
            raise CreativeValidationError(
                "Marketing Studio 이미지는 source_ui를 생성 후 합성하도록 설정해야 해요"
            )
    if spec.job_type in {"reframe", "brain_activity"}:
        video_inputs = [
            item for item in spec.input_files if item.mime_type.startswith("video/")
        ]
        if len(spec.input_files) != 1 or len(video_inputs) != 1:
            raise CreativeValidationError(
                f"{spec.job_type} 작업에는 video 입력 파일이 정확히 하나 필요해요"
            )
    if spec.job_type == "reframe" and spec.params.get("composite_source_ui") is True:
        raise CreativeValidationError(
            "reframe은 이미 합성된 원본을 변환하므로 source_ui를 다시 합성할 수 없어요"
        )
    if spec.job_type == "marketing_studio_video":
        invalid_params = []
        if spec.params.get("specific_mode") != "from_storyboard":
            invalid_params.append("specific_mode")
        if spec.params.get("generate_audio") is not False:
            invalid_params.append("generate_audio")
        if spec.params.get("resolution") != "1080p":
            invalid_params.append("resolution")
        if spec.params.get("composite_source_ui") is not True:
            invalid_params.append("composite_source_ui")
        if invalid_params:
            raise CreativeValidationError(
                "Marketing Studio 영상 설정이 승인 규칙과 달라요: "
                + ", ".join(invalid_params)
            )
        audio_inputs = [
            item for item in spec.input_files if item.mime_type.startswith("audio/")
        ]
        if len(audio_inputs) != 1 or audio_inputs[0].role != "voiceover":
            raise CreativeValidationError(
                "Marketing Studio 영상에는 대표의 실제 음성 voiceover 파일이 정확히 하나 필요해요"
            )
        source_ui_inputs = [
            item
            for item in spec.input_files
            if item.role == "source_ui"
            and (
                item.mime_type.startswith("image/")
                or item.mime_type.startswith("video/")
            )
        ]
        if len(source_ui_inputs) != 1:
            raise CreativeValidationError(
                "Marketing Studio 영상에는 합성할 실제 제품 화면 source_ui가 정확히 하나 필요해요"
            )
        storyboard_inputs = [
            item
            for item in spec.input_files
            if item.role == "storyboard" and item.mime_type.startswith("image/")
        ]
        if len(storyboard_inputs) != 1:
            raise CreativeValidationError(
                "Marketing Studio 영상에는 승인된 storyboard 이미지가 정확히 하나 필요해요"
            )
    allowed_hosts = {
        host.strip().lower()
        for host in settings.CREATIVE_INPUT_ALLOWED_HOSTS.split(",")
        if host.strip()
    }
    canonical_private_urls: dict[int, str] = {}
    for index, input_file in enumerate(spec.input_files):
        try:
            canonical_url = creative_input_assets.validate_manifest_asset(
                db, brief.id, input_file
            )
        except creative_input_assets.CreativeInputAssetError as exc:
            raise CreativeValidationError(str(exc)) from exc
        if canonical_url is not None:
            canonical_private_urls[index] = canonical_url
            continue
        if input_file.url.startswith("/"):
            continue
        hostname = (urlsplit(input_file.url).hostname or "").lower()
        if hostname not in allowed_hosts:
            raise CreativeValidationError(f"입력 자산 호스트가 허용되지 않았어요: {hostname}")
    if canonical_private_urls:
        spec_data = spec.model_dump(mode="json")
        for index, canonical_url in canonical_private_urls.items():
            spec_data["input_files"][index]["url"] = canonical_url
        spec = GenerationSpec.model_validate(spec_data)
    return spec


def _latest_attempt(brief: models.CreativeBrief) -> models.CreativeAttempt | None:
    return max(brief.attempts, key=lambda item: item.attempt_no, default=None)


def _virality_review(attempt: models.CreativeAttempt) -> tuple[list[str], list[str]]:
    report_output = next(
        (
            output
            for output in reversed(attempt.outputs)
            if output.kind == "virality_report" and isinstance(output.virality_json, dict)
        ),
        None,
    )
    if report_output is None:
        return ["virality_report_missing"], ["virality_report_missing"]
    report = report_output.virality_json or {}
    failures: list[str] = []
    warnings: list[str] = []
    if report.get("analysis_warning"):
        failures.append("virality_predictor_error")
        warnings.append("virality_predictor_error")
    hook_peak = report.get("hook_peak_seconds")
    sustain = report.get("sustain_score")
    if hook_peak is None:
        failures.append("hook_peak_seconds_missing")
        warnings.append("hook_peak_seconds_missing")
    else:
        try:
            hook_peak_value = float(hook_peak)
        except (TypeError, ValueError):
            hook_peak_value = math.nan
        if not math.isfinite(hook_peak_value) or hook_peak_value < 0:
            failures.append("hook_peak_seconds_invalid")
        elif hook_peak_value > 3:
            failures.append("hook_peak_after_3s")
    if sustain is None:
        failures.append("sustain_score_missing")
        warnings.append("sustain_score_missing")
    else:
        try:
            sustain_value = float(sustain)
        except (TypeError, ValueError):
            sustain_value = math.nan
        if math.isfinite(sustain_value) and sustain_value > 1:
            sustain_value /= 100
        if not math.isfinite(sustain_value) or not 0 <= sustain_value <= 1:
            failures.append("sustain_score_invalid")
        elif sustain_value < 0.7:
            failures.append("sustain_score_below_70pct")
    attention_overlap = report.get("attention_overlaps_product")
    if attention_overlap is False:
        failures.append("attention_misses_product")
    elif attention_overlap is None:
        failures.append("attention_overlap_missing")
        warnings.append("attention_overlap_missing")
    elif attention_overlap is not True:
        failures.append("attention_overlap_invalid")
    return failures, warnings


def _append_human_review(
    existing: dict[str, Any] | None,
    event: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(existing) if isinstance(existing, dict) else {}
    prior_history = merged.get("human_review_history")
    history = list(prior_history) if isinstance(prior_history, list) else []
    history.append(event)
    merged["human_review"] = event
    merged["human_review_history"] = history
    return merged


def approve_brief(
    db: Session,
    creative_id: str,
    *,
    admin_user_id: int,
    note: str | None = None,
    review_json: dict[str, Any] | None = None,
    override_reason: str | None = None,
) -> models.CreativeBrief:
    brief = get_brief(db, creative_id)
    now = utcnow()
    if brief.status in {"DRAFT", "STALE", "CHANGES_REQUESTED"}:
        validate_generation_spec(brief, db)
        brief.status = "BRIEF_APPROVED"
        brief.approved_by = admin_user_id
        brief.approved_at = now
    elif brief.status == "REVIEW_REQUIRED":
        attempt = _latest_attempt(brief)
        if attempt is None or attempt.status != "REVIEW_REQUIRED":
            raise CreativeConflict("검수할 생성 시도가 없어요")
        primary = next((output for output in attempt.outputs if output.is_primary), None)
        if primary is None:
            raise CreativeConflict("대표 최종 자산을 먼저 업로드해 주세요")
        failures, warnings = _virality_review(attempt)
        normalized_override = (override_reason or "").strip() or None
        if failures and normalized_override is None:
            raise CreativeConflict(
                "Virality 사전 기준을 통과하지 못했어요. "
                f"수정 요청하거나 예외 승인 사유를 남겨 주세요: {', '.join(failures)}"
            )
        human_review = {
            "decision": "APPROVED",
            "note": note,
            "details": review_json or {},
            "virality_failures": failures,
            "virality_warnings": warnings,
            "override_reason": normalized_override,
            "approved_by": admin_user_id,
            "approved_at": now.isoformat(),
        }
        primary.review_json = {
            **_append_human_review(primary.review_json, human_review),
            # Keep these summary fields for the existing admin/API consumer while
            # retaining runner provenance and the append-only human review event.
            "note": note,
            "virality_failures": failures,
            "virality_warnings": warnings,
            "override_reason": normalized_override,
            "approved_by": admin_user_id,
            "approved_at": now.isoformat(),
        }
        attempt.status = "APPROVED"
        attempt.completed_at = attempt.completed_at or now
        attempt.lease_expires_at = None
        brief.status = "APPROVED"
        brief.approved_by = admin_user_id
        brief.approved_at = now
    elif brief.status in {"BRIEF_APPROVED", "APPROVED", "PUBLISHED"}:
        return brief
    else:
        raise CreativeConflict(f"{brief.status} 상태는 승인할 수 없어요")
    db.commit()
    return get_brief(db, creative_id)


def queue_brief(db: Session, creative_id: str) -> models.CreativeAttempt:
    brief = get_brief(db, creative_id)
    spec = validate_generation_spec(brief, db)
    if brief.status not in {"BRIEF_APPROVED", "FAILED", "AUTH_REQUIRED"}:
        if brief.status == "QUEUED":
            latest = _latest_attempt(brief)
            if latest and latest.status == "QUEUED":
                return latest
        raise CreativeConflict(f"{brief.status} 상태는 큐에 넣을 수 없어요")

    spec_data = spec.model_dump(mode="json")
    prompt_sha = hashlib.sha256(spec.prompt.encode("utf-8")).hexdigest()
    input_hash = _canonical_hash(
        {
            "creative_id": brief.id,
            "version": brief.version,
            "source_hash": brief.source_hash,
            "spec": spec_data,
        }
    )
    duplicate = (
        db.query(models.CreativeAttempt)
        .filter(
            models.CreativeAttempt.creative_id == creative_id,
            models.CreativeAttempt.input_hash == input_hash,
            models.CreativeAttempt.status.in_(
                ["QUEUED", "CLAIMED", "GENERATING", "PROCESSING", "REVIEW_REQUIRED", "APPROVED"]
            ),
        )
        .order_by(models.CreativeAttempt.attempt_no.desc())
        .first()
    )
    if duplicate is not None:
        return duplicate

    max_no = (
        db.query(func.max(models.CreativeAttempt.attempt_no))
        .filter(models.CreativeAttempt.creative_id == creative_id)
        .scalar()
        or 0
    )
    attempt = models.CreativeAttempt(
        creative_id=creative_id,
        attempt_no=max_no + 1,
        job_type=spec.job_type,
        prompt=spec.prompt,
        params_json=spec.params,
        input_files_json=[item.model_dump(mode="json") for item in spec.input_files],
        prompt_sha256=prompt_sha,
        input_hash=input_hash,
        status="QUEUED",
    )
    db.add(attempt)
    brief.status = "QUEUED"
    db.commit()
    db.refresh(attempt)
    return attempt


def request_changes(
    db: Session,
    creative_id: str,
    *,
    reason: str,
    review_json: dict[str, Any] | None = None,
) -> models.CreativeBrief:
    brief = get_brief(db, creative_id)
    if brief.status not in {"REVIEW_REQUIRED", "APPROVED", "AUTH_REQUIRED", "FAILED"}:
        raise CreativeConflict(f"{brief.status} 상태에서는 수정을 요청할 수 없어요")
    attempt = _latest_attempt(brief)
    now = utcnow()
    if attempt is not None:
        attempt.status = "CHANGES_REQUESTED"
        attempt.error = reason
        attempt.lease_expires_at = None
        for output in attempt.outputs:
            if output.is_primary:
                human_review = {
                    "decision": "CHANGES_REQUESTED",
                    "reason": reason,
                    "details": review_json or {},
                    "requested_at": now.isoformat(),
                }
                output.review_json = {
                    **_append_human_review(output.review_json, human_review),
                    "changes_requested": reason,
                    "changes_requested_at": now.isoformat(),
                }
    brief.status = "CHANGES_REQUESTED"
    brief.approved_by = None
    brief.approved_at = None
    db.commit()
    return get_brief(db, creative_id)


def mark_published(
    db: Session,
    creative_id: str,
    *,
    published_at: datetime | None = None,
) -> models.CreativeBrief:
    brief = get_brief(db, creative_id)
    if brief.status == "PUBLISHED":
        return brief
    if brief.status != "APPROVED":
        raise CreativeConflict("검수 승인된 자산만 게시 처리할 수 있어요")
    attempt = _latest_attempt(brief)
    if attempt is None or not any(output.is_primary for output in attempt.outputs):
        raise CreativeConflict("게시할 대표 자산이 없어요")
    brief.status = "PUBLISHED"
    brief.published_at = _naive_utc(published_at) if published_at else utcnow()
    attempt.status = "PUBLISHED"
    db.commit()
    return get_brief(db, creative_id)


def _absolute_input_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    web_base = settings.PUBLIC_WEB_URL.rstrip("/") + "/"
    api_base = settings.PUBLIC_API_URL.rstrip("/") + "/"
    result: list[dict[str, Any]] = []
    for item in files:
        copied = dict(item)
        relative_url = str(copied.get("url", ""))
        if relative_url.startswith("/"):
            base = (
                api_base
                if creative_input_assets.RUNNER_INPUT_PATH_RE.fullmatch(relative_url)
                else web_base
            )
            copied["url"] = urljoin(base, relative_url.lstrip("/"))
        result.append(copied)
    return result


def _claim_payload(attempt: models.CreativeAttempt) -> dict[str, Any]:
    return {
        "attempt_id": attempt.id,
        "creative_id": attempt.creative_id,
        "attempt_no": attempt.attempt_no,
        "brief_format": attempt.brief.format,
        "hook": attempt.brief.hook,
        "body_copy": attempt.brief.body_copy,
        "cta_copy": attempt.brief.cta_copy,
        "job_type": attempt.job_type,
        "prompt": attempt.prompt,
        "params_json": attempt.params_json or {},
        "input_files_json": _absolute_input_files(attempt.input_files_json or []),
        "input_hash": attempt.input_hash,
        "higgsfield_job_id": attempt.higgsfield_job_id,
        "virality_job_id": attempt.virality_job_id,
        "lease_expires_at": attempt.lease_expires_at,
    }


def claim_attempt(
    db: Session,
    *,
    runner_id: str,
    cli_version: str,
) -> dict[str, Any] | None:
    if cli_version != settings.HIGGSFIELD_CLI_VERSION:
        raise CreativeConflict(
            f"Higgsfield CLI {settings.HIGGSFIELD_CLI_VERSION} 버전이 필요해요"
        )
    now = utcnow()
    lease_seconds = max(60, min(settings.CREATIVE_RUNNER_LEASE_SECONDS, 3600))
    is_postgresql = db.bind is not None and db.bind.dialect.name == "postgresql"
    if is_postgresql:
        # HTTP 응답이 유실되어 같은 runner가 claim을 재시도해도 다른 작업을
        # 가져가지 않게 runner id 단위로 짧은 transaction advisory lock을 잡는다.
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:runner_id, 0))"),
            {"runner_id": runner_id},
        )
    live_attempt = (
        db.query(models.CreativeAttempt)
        .filter(
            models.CreativeAttempt.runner_id == runner_id,
            models.CreativeAttempt.status.in_(list(ACTIVE_ATTEMPT_STATUSES)),
            models.CreativeAttempt.lease_expires_at > now,
        )
        .order_by(models.CreativeAttempt.started_at, models.CreativeAttempt.id)
        .first()
    )
    if live_attempt is not None:
        live_attempt.lease_expires_at = now + timedelta(seconds=lease_seconds)
        live_attempt.cli_version = cli_version
        db.commit()
        return _claim_payload(live_attempt)

    # 큐 대기 행과 lease가 만료된 행을 **한 번의 row lock** 안에서
    # claim한다. 만료 행을 먼저 QUEUED로 일괄 UPDATE하면 두
    # runner가 겹칠 때 나중 transaction이 앞의 CLAIMED를 덮어쓰는
    # lost-update가 생길 수 있다.
    expired_active = and_(
        models.CreativeAttempt.status.in_(list(ACTIVE_ATTEMPT_STATUSES)),
        or_(
            models.CreativeAttempt.lease_expires_at.is_(None),
            models.CreativeAttempt.lease_expires_at <= now,
        ),
    )
    query = db.query(models.CreativeAttempt).filter(
        or_(models.CreativeAttempt.status == "QUEUED", expired_active)
    )
    if is_postgresql:
        query = query.with_for_update(skip_locked=True)
    attempt = query.order_by(
        case((expired_active, 0), else_=1),
        models.CreativeAttempt.created_at,
        models.CreativeAttempt.id,
    ).first()
    if attempt is None:
        return None
    was_expired = attempt.status in ACTIVE_ATTEMPT_STATUSES
    attempt.runner_id = runner_id
    attempt.cli_version = cli_version
    attempt.status = "CLAIMED"
    attempt.started_at = attempt.started_at or now
    attempt.lease_expires_at = now + timedelta(seconds=lease_seconds)
    attempt.error = (
        "runner lease expired; check the existing Higgsfield job before retry"
        if was_expired and attempt.higgsfield_job_id
        else None
    )
    attempt.brief.status = "CLAIMED"
    db.commit()
    db.refresh(attempt)
    return _claim_payload(attempt)


def _runner_attempt(
    db: Session,
    attempt_id: int,
    *,
    runner_id: str | None = None,
    require_live_lease: bool = True,
) -> models.CreativeAttempt:
    attempt = (
        db.query(models.CreativeAttempt)
        .options(selectinload(models.CreativeAttempt.outputs))
        .filter(models.CreativeAttempt.id == attempt_id)
        .first()
    )
    if attempt is None:
        raise CreativeNotFound("생성 시도를 찾을 수 없어요")
    if runner_id is not None and attempt.runner_id != runner_id:
        raise CreativeConflict("다른 runner가 점유한 작업이에요")
    if require_live_lease:
        if attempt.lease_expires_at is None or attempt.lease_expires_at <= utcnow():
            raise CreativeConflict("runner lease가 만료됐어요. 작업을 다시 claim하세요")
    return attempt


def heartbeat(
    db: Session,
    attempt_id: int,
    *,
    runner_id: str,
    status: str | None = None,
    higgsfield_job_id: str | None = None,
    virality_job_id: str | None = None,
) -> models.CreativeAttempt:
    attempt = _runner_attempt(db, attempt_id, runner_id=runner_id)
    if attempt.status not in ACTIVE_ATTEMPT_STATUSES:
        raise CreativeConflict(f"{attempt.status} 상태는 heartbeat를 받을 수 없어요")
    if status:
        allowed = {
            "CLAIMED": {"GENERATING", "PROCESSING"},
            "GENERATING": {"GENERATING", "PROCESSING"},
            "PROCESSING": {"PROCESSING"},
        }
        if status not in allowed[attempt.status]:
            raise CreativeConflict(f"{attempt.status}→{status} 전환은 허용되지 않아요")
        attempt.status = status
        attempt.brief.status = status
    if higgsfield_job_id:
        if attempt.higgsfield_job_id and attempt.higgsfield_job_id != higgsfield_job_id:
            raise CreativeConflict("이 시도에 다른 Higgsfield job id가 이미 등록돼 있어요")
        attempt.higgsfield_job_id = higgsfield_job_id
    if virality_job_id:
        if attempt.virality_job_id and attempt.virality_job_id != virality_job_id:
            raise CreativeConflict("이 시도에 다른 Virality job id가 이미 등록돼 있어요")
        attempt.virality_job_id = virality_job_id
    lease_seconds = max(60, min(settings.CREATIVE_RUNNER_LEASE_SECONDS, 3600))
    attempt.lease_expires_at = utcnow() + timedelta(seconds=lease_seconds)
    db.commit()
    db.refresh(attempt)
    return attempt


def fail_attempt(
    db: Session,
    attempt_id: int,
    *,
    runner_id: str,
    error: str,
    auth_required: bool,
    retryable: bool,
) -> models.CreativeAttempt:
    attempt = _runner_attempt(
        db,
        attempt_id,
        runner_id=runner_id,
        require_live_lease=False,
    )
    if attempt.status not in ACTIVE_ATTEMPT_STATUSES | {"REVIEW_REQUIRED"}:
        raise CreativeConflict(f"{attempt.status} 상태는 실패 처리할 수 없어요")
    next_status = "AUTH_REQUIRED" if auth_required else "FAILED"
    attempt.status = next_status
    attempt.brief.status = next_status
    attempt.error = f"{'retryable: ' if retryable else ''}{error}"[:1000]
    attempt.completed_at = utcnow()
    attempt.lease_expires_at = None
    db.commit()
    db.refresh(attempt)
    return attempt


def _detect_mime(header: bytes) -> str | None:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return "video/mp4"
    stripped = header.lstrip()
    if stripped.startswith((b"{", b"[")):
        return "application/json"
    return None


def _validate_image(path: Path, mime_type: str) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            expected_format = {
                "image/png": "PNG",
                "image/jpeg": "JPEG",
                "image/webp": "WEBP",
            }[mime_type]
            if image.format != expected_format:
                raise CreativeValidationError("파일 내용과 MIME 형식이 달라요")
            width, height = image.size
            image.verify()
    except CreativeValidationError:
        raise
    except Exception as exc:
        raise CreativeValidationError("올바른 이미지 파일이 아니에요") from exc
    if width <= 0 or height <= 0 or width * height > 50_000_000:
        raise CreativeValidationError("이미지 해상도가 허용 범위를 벗어났어요")
    return width, height


def _validate_mp4(path: Path) -> tuple[int, int, int, bool]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise CreativeValidationError("MP4 코덱을 검증할 ffprobe가 서버에 없어요")
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,codec_name,pix_fmt,width,height",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        info = json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise CreativeValidationError("올바른 MP4 파일이 아니에요") from exc
    video = next((stream for stream in info.get("streams", []) if stream.get("codec_type") == "video"), None)
    if not video or video.get("codec_name") != "h264" or video.get("pix_fmt") != "yuv420p":
        raise CreativeValidationError("최종 MP4는 H.264/yuv420p 형식이어야 해요")
    audio = [stream for stream in info.get("streams", []) if stream.get("codec_type") == "audio"]
    if any(stream.get("codec_name") != "aac" for stream in audio):
        raise CreativeValidationError("MP4 오디오는 AAC 형식이어야 해요")
    with path.open("rb") as stream:
        first_mb = stream.read(1024 * 1024)
    moov = first_mb.find(b"moov")
    mdat = first_mb.find(b"mdat")
    if moov < 0 or mdat < 0 or moov > mdat:
        raise CreativeValidationError("MP4에 faststart(moov before mdat)가 적용되지 않았어요")
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    duration_ms = round(float((info.get("format") or {}).get("duration") or 0) * 1000)
    if width <= 0 or height <= 0 or duration_ms <= 0:
        raise CreativeValidationError("MP4 해상도와 길이를 확인할 수 없어요")
    return width, height, duration_ms, bool(audio)


def _validate_dimensions(
    brief_format: str,
    kind: str,
    width: int | None,
    height: int | None,
) -> None:
    expected = _EXPECTED_DIMENSIONS.get(brief_format)
    if expected is None or kind in {"original", "thumbnail", "virality_report"}:
        return
    if (width, height) != expected:
        raise CreativeValidationError(
            f"{brief_format} 최종 자산은 {expected[0]}x{expected[1]}이어야 해요"
        )


async def store_output(
    db: Session,
    attempt_id: int,
    *,
    upload: UploadFile,
    runner_id: str,
    kind: str,
    is_primary: bool,
    metadata: dict[str, Any],
    expected_sha256: str | None,
) -> models.CreativeOutput:
    attempt = _runner_attempt(db, attempt_id, runner_id=runner_id)
    if attempt.status not in RUNNER_OUTPUT_STATUSES:
        raise CreativeConflict(f"{attempt.status} 상태는 결과를 올릴 수 없어요")
    if kind not in OUTPUT_KINDS:
        raise CreativeValidationError("허용되지 않은 결과 종류예요")
    if is_primary and kind not in FINAL_PRIMARY_KINDS:
        raise CreativeValidationError("대표 자산은 final_png, webp, mp4 중 하나여야 해요")
    if "virality" in metadata:
        raise CreativeValidationError(
            "Virality 결과는 인증된 virality_report JSON 파일로만 올릴 수 있어요"
        )
    declared_mime = (upload.content_type or "").lower().split(";", 1)[0].strip()
    if declared_mime not in _KIND_MIMES[kind]:
        raise CreativeValidationError(f"{kind}에 허용되지 않은 MIME 형식이에요")
    extension = Path(upload.filename or "").suffix.lower()
    canonical_extension, allowed_extensions = _MIME_EXTENSIONS[declared_mime]
    if extension not in allowed_extensions:
        raise CreativeValidationError("파일 확장자와 MIME 형식이 달라요")
    if expected_sha256:
        expected_sha256 = expected_sha256.lower().strip()
        if len(expected_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in expected_sha256):
            raise CreativeValidationError("sha256은 64자 16진수여야 해요")

    root = Path(settings.CREATIVE_ASSET_ROOT).expanduser().resolve()
    target_dir = (root / attempt.creative_id / str(attempt.attempt_no)).resolve()
    if root != target_dir and root not in target_dir.parents:
        raise CreativeValidationError("자산 저장 경로가 안전하지 않아요")
    target_dir.mkdir(parents=True, exist_ok=True, mode=0o755)
    # Named volume를 read-only로 마운트한 nginx worker가 파생물을 읽을 수
    # 있어야 한다. 서브디렉터리는 시크릿을 담지 않으므로 0755.
    target_dir.chmod(0o755)
    max_bytes = max(1, settings.CREATIVE_MAX_UPLOAD_BYTES)
    if declared_mime.startswith("image/"):
        max_bytes = min(max_bytes, 25 * 1024 * 1024)
    elif declared_mime == "application/json":
        max_bytes = min(max_bytes, 5 * 1024 * 1024)

    temp_path: Path | None = None
    final_path: Path | None = None
    try:
        digest = hashlib.sha256()
        size = 0
        header = b""
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".upload-",
            suffix=canonical_extension,
            dir=target_dir,
            delete=False,
        ) as temp:
            temp_path = Path(temp.name)
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise CreativeValidationError(f"파일 크기가 {max_bytes}바이트 한도를 넘었어요")
                if len(header) < 64:
                    header += chunk[: 64 - len(header)]
                digest.update(chunk)
                temp.write(chunk)
        if size == 0:
            raise CreativeValidationError("빈 파일은 올릴 수 없어요")
        actual_mime = _detect_mime(header)
        if actual_mime != declared_mime:
            raise CreativeValidationError("파일 실제 형식과 선언한 MIME이 달라요")
        actual_sha = digest.hexdigest()
        if expected_sha256 and not secrets.compare_digest(actual_sha, expected_sha256):
            raise CreativeValidationError("서버에서 계산한 sha256과 runner 값이 달라요")

        width: int | None = None
        height: int | None = None
        duration_ms: int | None = None
        has_audio = False
        virality: dict[str, Any] | None = None
        if declared_mime.startswith("image/"):
            width, height = _validate_image(temp_path, declared_mime)
        elif declared_mime == "video/mp4":
            width, height, duration_ms, has_audio = _validate_mp4(temp_path)
        else:
            try:
                loaded = json.loads(temp_path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CreativeValidationError("올바른 JSON 보고서가 아니에요") from exc
            if not isinstance(loaded, dict):
                raise CreativeValidationError("Virality 보고서는 JSON object여야 해요")
            virality = _validate_virality_report(
                loaded,
                expected_generation_job_id=attempt.higgsfield_job_id,
                expected_predictor_job_id=attempt.virality_job_id,
            )
        _validate_dimensions(attempt.brief.format, kind, width, height)
        if kind == "mp4" and is_primary and not has_audio:
            raise CreativeValidationError("대표 영상에는 AAC 음성 트랙이 필요해요")

        duplicate = (
            db.query(models.CreativeOutput)
            .filter(
                models.CreativeOutput.attempt_id == attempt.id,
                models.CreativeOutput.kind == kind,
                models.CreativeOutput.sha256 == actual_sha,
            )
            .first()
        )
        if duplicate is not None:
            if is_primary and not duplicate.is_primary:
                db.query(models.CreativeOutput).filter(
                    models.CreativeOutput.attempt_id == attempt.id
                ).update({models.CreativeOutput.is_primary: False}, synchronize_session=False)
                duplicate.is_primary = True
                attempt.status = "REVIEW_REQUIRED"
                attempt.brief.status = "REVIEW_REQUIRED"
                attempt.completed_at = attempt.completed_at or utcnow()
                db.commit()
            return duplicate

        filename = f"{kind}-{secrets.token_hex(8)}{canonical_extension}"
        final_path = target_dir / filename
        os.replace(temp_path, final_path)
        final_path.chmod(0o644)
        temp_path = None
        relative_path = final_path.relative_to(root).as_posix()
        base_url = settings.CREATIVE_ASSET_BASE_URL.rstrip("/")
        public_url = f"{base_url}/{relative_path}"
        output = models.CreativeOutput(
            attempt_id=attempt.id,
            kind=kind,
            storage_path=relative_path,
            public_url=public_url,
            sha256=actual_sha,
            mime_type=actual_mime,
            size_bytes=size,
            width=width,
            height=height,
            duration_ms=duration_ms,
            review_json=metadata.get("review") if isinstance(metadata.get("review"), dict) else None,
            virality_json=virality,
            is_primary=is_primary,
        )
        if is_primary:
            db.query(models.CreativeOutput).filter(
                models.CreativeOutput.attempt_id == attempt.id
            ).update({models.CreativeOutput.is_primary: False}, synchronize_session=False)
            attempt.status = "REVIEW_REQUIRED"
            attempt.brief.status = "REVIEW_REQUIRED"
            attempt.completed_at = attempt.completed_at or utcnow()
        elif attempt.job_type == "brain_activity" and kind == "virality_report":
            # report-only 분석 시도도 runner 관점에서는 완료다. 대표 자산이 필요한
            # 최종 게시는 계속 admin 승인 규칙이 막고, 운영자는 보고서를 검수하거나
            # 수정 요청할 수 있다.
            attempt.status = "REVIEW_REQUIRED"
            attempt.brief.status = "REVIEW_REQUIRED"
            attempt.completed_at = attempt.completed_at or utcnow()
        elif attempt.status in {"CLAIMED", "GENERATING"}:
            attempt.status = "PROCESSING"
            attempt.brief.status = "PROCESSING"
        db.add(output)
        db.commit()
        db.refresh(output)
        return output
    except Exception:
        db.rollback()
        if final_path is not None and final_path.exists():
            final_path.unlink()
        raise
    finally:
        await upload.close()
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
