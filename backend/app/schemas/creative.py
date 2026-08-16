"""Higgsfield creative workflow API schemas."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


CreativeStatus = Literal[
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
]
AttemptStatus = Literal[
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
]
OutputKind = Literal[
    "original",
    "final_png",
    "webp",
    "mp4",
    "poster",
    "thumbnail",
    "virality_report",
]

_KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _validate_key(value: str) -> str:
    value = value.strip()
    if not _KEY_RE.fullmatch(value):
        raise ValueError("영문·숫자와 _ . : - 만 사용할 수 있어요")
    return value


def _validate_landing_path(value: str) -> str:
    value = value.strip()
    parsed = urlsplit(value)
    decoded_path = unquote(parsed.path)
    if (
        not value.startswith("/")
        or value.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or parsed.fragment
        or "\\" in value
        or "\\" in decoded_path
        or any(ord(ch) < 32 for ch in value)
        or any(ord(ch) < 32 for ch in decoded_path)
        or ".." in decoded_path.split("/")
    ):
        raise ValueError("랜딩은 동일 사이트의 절대경로(/...)만 사용할 수 있어요")
    return value


class CreativeInputFile(BaseModel):
    url: str = Field(min_length=1, max_length=1000)
    sha256: str
    mime_type: Literal[
        "image/png",
        "image/jpeg",
        "image/webp",
        "video/mp4",
        "audio/mpeg",
        "audio/wav",
    ]
    role: Literal["source_ui", "reference", "storyboard", "voiceover"] = "reference"

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        value = value.lower().strip()
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("sha256은 64자 16진수여야 해요")
        return value

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.strip()
        parsed = urlsplit(value)
        if value.startswith("/") and not value.startswith("//"):
            if ".." in parsed.path.split("/") or "\\" in value:
                raise ValueError("상대 자산 경로가 안전하지 않아요")
            return value
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("입력 자산은 HTTPS URL 또는 동일 사이트 경로여야 해요")
        return value


class CreativeInputAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    creative_id: str
    role: Literal["source_ui", "reference", "storyboard", "voiceover"]
    original_filename: str
    storage_path: str
    sha256: str
    mime_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    media_metadata_json: dict[str, Any]
    created_by: int | None = None
    created_at: datetime


class CreativeInputAssetUploadOut(CreativeInputAssetOut):
    manifest: CreativeInputFile
    preview_url: str


class GenerationSpec(BaseModel):
    job_type: Literal[
        "gpt_image_2",
        "marketing_studio_image",
        "marketing_studio_video",
        "reframe",
        "brain_activity",
    ]
    prompt: str = Field(default="", max_length=30_000)
    params: dict[str, Any] = Field(default_factory=dict)
    input_files: list[CreativeInputFile] = Field(default_factory=list, max_length=10)


class CreativeBriefCreate(BaseModel):
    source_type: str = Field(default="manual", min_length=1, max_length=30)
    source_ref_id: str | None = Field(default=None, max_length=120)
    source_hash: str | None = Field(default=None, max_length=64)
    campaign_key: str = Field(min_length=1, max_length=120)
    concept_key: str = Field(min_length=1, max_length=80)
    variant: str = Field(default="A", min_length=1, max_length=20)
    channel: str = Field(min_length=1, max_length=40)
    format: str = Field(min_length=1, max_length=40)
    hook: str = Field(min_length=1, max_length=500)
    body_copy: str = Field(default="", max_length=10_000)
    cta_copy: str = Field(min_length=1, max_length=200)
    landing_path: str = Field(min_length=1, max_length=500)
    utm_source: str | None = Field(default=None, max_length=120)
    utm_medium: str | None = Field(default=None, max_length=120)
    utm_campaign: str | None = Field(default=None, max_length=160)
    generation_spec_json: dict[str, Any] = Field(default_factory=dict)

    _campaign_key = field_validator("campaign_key")(_validate_key)
    _concept_key = field_validator("concept_key")(_validate_key)
    _landing_path = field_validator("landing_path")(_validate_landing_path)

    @field_validator("source_hash")
    @classmethod
    def validate_source_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.lower().strip()
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("source_hash는 64자 sha256이어야 해요")
        return value


class CreativeBriefUpdate(BaseModel):
    source_type: str | None = Field(default=None, min_length=1, max_length=30)
    source_ref_id: str | None = Field(default=None, max_length=120)
    source_hash: str | None = Field(default=None, max_length=64)
    campaign_key: str | None = Field(default=None, min_length=1, max_length=120)
    concept_key: str | None = Field(default=None, min_length=1, max_length=80)
    variant: str | None = Field(default=None, min_length=1, max_length=20)
    channel: str | None = Field(default=None, min_length=1, max_length=40)
    format: str | None = Field(default=None, min_length=1, max_length=40)
    hook: str | None = Field(default=None, min_length=1, max_length=500)
    body_copy: str | None = Field(default=None, max_length=10_000)
    cta_copy: str | None = Field(default=None, min_length=1, max_length=200)
    landing_path: str | None = Field(default=None, min_length=1, max_length=500)
    utm_source: str | None = Field(default=None, max_length=120)
    utm_medium: str | None = Field(default=None, max_length=120)
    utm_campaign: str | None = Field(default=None, max_length=160)
    generation_spec_json: dict[str, Any] | None = None

    _campaign_key = field_validator("campaign_key")(
        lambda value: _validate_key(value) if value is not None else value
    )
    _concept_key = field_validator("concept_key")(
        lambda value: _validate_key(value) if value is not None else value
    )
    _landing_path = field_validator("landing_path")(
        lambda value: _validate_landing_path(value) if value is not None else value
    )

    @field_validator("source_hash")
    @classmethod
    def validate_source_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.lower().strip()
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("source_hash는 64자 sha256이어야 해요")
        return value


class CreativeOutputOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    attempt_id: int
    kind: OutputKind
    storage_path: str
    public_url: str
    sha256: str
    mime_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    review_json: dict[str, Any] | None = None
    virality_json: dict[str, Any] | None = None
    is_primary: bool
    created_at: datetime


class CreativeAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    creative_id: str
    attempt_no: int
    runner_id: str | None = None
    lease_expires_at: datetime | None = None
    cli_version: str | None = None
    job_type: str
    prompt: str
    params_json: dict[str, Any]
    input_files_json: list[dict[str, Any]]
    prompt_sha256: str
    input_hash: str
    higgsfield_job_id: str | None = None
    virality_job_id: str | None = None
    status: AttemptStatus
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    outputs: list[CreativeOutputOut] = Field(default_factory=list)


class CreativeBriefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_type: str
    source_ref_id: str | None = None
    source_hash: str | None = None
    campaign_key: str
    concept_key: str
    variant: str
    channel: str
    format: str
    hook: str
    body_copy: str
    cta_copy: str
    landing_path: str
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    generation_spec_json: dict[str, Any]
    version: int
    status: CreativeStatus
    approved_by: int | None = None
    approved_at: datetime | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    attempts: list[CreativeAttemptOut] = Field(default_factory=list)


class CreativeApproveRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)
    review_json: dict[str, Any] | None = None
    override_reason: str | None = Field(default=None, max_length=1000)


class CreativeChangesRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    review_json: dict[str, Any] | None = None


class CreativePublishedRequest(BaseModel):
    published_at: datetime | None = None


class RunnerClaimRequest(BaseModel):
    runner_id: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.:-]+$")
    cli_version: str = Field(min_length=1, max_length=30)


class RunnerClaimOut(BaseModel):
    attempt_id: int
    creative_id: str
    attempt_no: int
    brief_format: str
    hook: str
    body_copy: str
    cta_copy: str
    job_type: str
    prompt: str
    params_json: dict[str, Any]
    input_files_json: list[dict[str, Any]]
    input_hash: str
    higgsfield_job_id: str | None = None
    virality_job_id: str | None = None
    lease_expires_at: datetime


class RunnerHeartbeatRequest(BaseModel):
    runner_id: str = Field(min_length=1, max_length=120)
    status: Literal["GENERATING", "PROCESSING"] | None = None
    higgsfield_job_id: str | None = Field(default=None, max_length=160)
    virality_job_id: str | None = Field(default=None, max_length=160)


class RunnerHeartbeatOut(BaseModel):
    attempt_id: int
    status: AttemptStatus
    lease_expires_at: datetime


class RunnerFailRequest(BaseModel):
    runner_id: str = Field(min_length=1, max_length=120)
    error: str = Field(min_length=1, max_length=1000)
    auth_required: bool = False
    retryable: bool = False


class RunnerFailOut(BaseModel):
    attempt_id: int
    status: AttemptStatus


class RunnerOutputResponse(BaseModel):
    output: CreativeOutputOut
    attempt_status: AttemptStatus
    creative_status: CreativeStatus
