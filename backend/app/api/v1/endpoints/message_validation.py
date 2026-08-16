"""허가형 링크로만 여는 비보조 5초 메시지 이해도 테스트.

개인 연락처는 받지 않는다. 참가자는 브라우저에 저장되는 무작위 토큰으로 같은
메시지에 고정되고, 서버는 같은 모집 코호트 안에서 A/B 수를 맞춘다. 이 결과는
통계적 승자 선언이 아니라 사전등록된 탈락/진출 게이트에만 쓴다.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from math import ceil
from statistics import median

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.db import models
from app.db.session import get_db


router = APIRouter()

CAMPAIGN_KEY = "message_validation_202608"
CODING_VERSION = "ko-v1"
VARIANT_COPY = {
    "A": {
        "headline": "나라장터 공고 옆에서, 자격·A값·하한선을 한 번에.",
        "role": "mechanism",
    },
    "B": {
        "headline": "이 공고, 우리 회사가 진짜 넣어도 될까요?",
        "role": "qualification_anxiety",
    },
}
COMMON_COPY = {
    "description": (
        "보고 있는 공고 화면에서 참가조건·계산 기준·주의 조항을 확인하세요. "
        "낙찰가는 예측하지 않습니다."
    ),
    "cta": "이 공고 확인하기",
    "endline": "투찰 전 마지막 확인, BidEasy.",
}


class ScreeningRequest(BaseModel):
    access_key: str = Field(min_length=1, max_length=240)
    participant_token: str | None = Field(default=None, min_length=20, max_length=80)
    industry: str = Field(min_length=1, max_length=40)
    staff_count: int = Field(ge=1, le=500)
    directly_handles_bids: bool
    monthly_notice_reviews: int = Field(ge=0, le=10000)


class ResponseRequest(BaseModel):
    access_key: str = Field(min_length=1, max_length=240)
    participant_token: str = Field(min_length=20, max_length=80)
    exposure_ms: int = Field(ge=0, le=120000)
    service_understanding: str = Field(min_length=1, max_length=1000)
    usage_moment: str = Field(min_length=1, max_length=1000)
    checked_items: str = Field(min_length=1, max_length=1000)
    trust_score: int = Field(ge=1, le=5)
    relevance_score: int = Field(ge=1, le=5)


def _configured_access_keys() -> list[str]:
    raw = settings.MESSAGE_TEST_ACCESS_KEYS or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


def _cohort_for(access_key: str) -> str:
    if not settings.MESSAGE_TEST_ENABLED:
        raise HTTPException(status_code=404, detail="현재 모집 중인 테스트가 아닙니다.")
    keys = _configured_access_keys()
    if not keys or not any(hmac.compare_digest(access_key, key) for key in keys):
        raise HTTPException(status_code=403, detail="승인된 테스트 링크가 아닙니다.")
    return hashlib.sha256(access_key.encode("utf-8")).hexdigest()[:16]


def _configured_test_image() -> tuple[str, str]:
    path = (settings.MESSAGE_TEST_IMAGE_PATH or "").strip()
    caption = (settings.MESSAGE_TEST_IMAGE_CAPTION or "").strip()
    allowed_prefixes = ("/guide-assets/", "/assets/generated/")
    unsafe = (
        not path
        or not caption
        or not path.startswith(allowed_prefixes)
        or "\\" in path
        or "%" in path
        or "?" in path
        or "#" in path
        or any(part in {"", ".", ".."} for part in path.split("/")[1:])
        or "공고번호" not in caption
        or "기준" not in caption
        or not any(source in caption for source in ("공개 G2B", "나라장터"))
    )
    if unsafe:
        raise HTTPException(
            status_code=503,
            detail="메시지 테스트용 승인 화면이 아직 설정되지 않았습니다.",
        )
    return path, caption[:500]


def _eligible(req: ScreeningRequest) -> bool:
    normalized = req.industry.strip().lower().replace(" ", "")
    target_industry = normalized in {
        "전기", "전기공사", "전기공사업", "전문", "전문공사", "전문건설", "전문건설업",
    }
    return (
        target_industry
        and 1 <= req.staff_count <= 10
        and req.directly_handles_bids
        and req.monthly_notice_reviews >= 10
    )


def _lock_assignment_cohort(db: Session, cohort_key: str) -> None:
    """PostgreSQL에서 cohort별 count→insert 구간을 직렬화한다.

    둘 이상의 요청이 동시에 같은 count를 읽으면 모두 같은 variant를 고를 수 있다.
    transaction advisory lock은 별도 잠금 테이블 없이 현재 commit까지 그 경합만 막는다.
    테스트·로컬 SQLite에는 해당 함수가 없으므로 의도적으로 no-op이다.
    """
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return
    digest = hashlib.sha256(f"{CAMPAIGN_KEY}:{cohort_key}".encode("utf-8")).digest()
    lock_key = int.from_bytes(digest[:8], byteorder="big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})


def _assign_variant(db: Session, cohort_key: str) -> str:
    _lock_assignment_cohort(db, cohort_key)
    rows = (
        db.query(models.MessageTestParticipant.variant, func.count(models.MessageTestParticipant.id))
        .filter(
            models.MessageTestParticipant.campaign_key == CAMPAIGN_KEY,
            models.MessageTestParticipant.cohort_key == cohort_key,
        )
        .group_by(models.MessageTestParticipant.variant)
        .all()
    )
    counts = {"A": 0, "B": 0}
    counts.update({variant: int(count) for variant, count in rows})
    if counts["A"] == counts["B"]:
        return secrets.choice(("A", "B"))
    return "A" if counts["A"] < counts["B"] else "B"


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    compact = " ".join(text.lower().split())
    return any(term in compact for term in terms)


def code_response(service: str, moment: str, items: str) -> dict:
    """사전등록된 네 코드와 낙찰가 예측 오해를 기계적으로 1차 코딩한다."""
    combined = f"{service} {moment} {items}"
    codes = {
        "public_procurement": _contains(
            combined, ("나라장터", "g2b", "공공입찰", "공공 입찰", "전자입찰", "조달"),
        ),
        "before_bid": _contains(
            combined, ("투찰 전", "투찰하기 전", "제출 전", "제출하기 전", "입찰 전", "넣기 전"),
        ),
        "concrete_check": _contains(
            combined,
            ("자격", "면허", "참가조건", "참가 조건", "a값", "a 값", "에이값", "하한선", "낙찰하한"),
        ),
        "same_screen": _contains(
            combined, ("공고 옆", "화면 옆", "사이드패널", "사이드 패널", "한 화면", "같은 화면", "화면 안", "떠나지"),
        ),
    }
    predicts_price = _contains(
        combined,
        (
            "낙찰가 예측", "낙찰 가격 예측", "낙찰가를 예측", "낙찰가를 맞", "낙찰 가격을 맞",
            "낙찰가를 알려", "낙찰 가격을 알려",
        ),
    )
    return {
        "version": CODING_VERSION,
        "codes": codes,
        "codes_hit": sum(1 for value in codes.values() if value),
        "prediction_misunderstood": predicts_price,
    }


def _assignment_payload(row: models.MessageTestParticipant) -> dict:
    image_path, image_caption = _configured_test_image()
    return {
        "eligible": True,
        "participant_token": row.participant_token,
        "variant": row.variant,
        "copy": {**VARIANT_COPY[row.variant], **COMMON_COPY},
        "image_path": image_path,
        "image_caption": image_caption,
        "display_ms": 5000,
        "already_submitted": row.submitted_at is not None,
    }


@router.post("/assign")
@limiter.limit("12/hour")
def assign_message(
    request: Request,
    body: ScreeningRequest,
    db: Session = Depends(get_db),
):
    cohort_key = _cohort_for(body.access_key)
    _configured_test_image()
    if body.participant_token:
        existing = (
            db.query(models.MessageTestParticipant)
            .filter(models.MessageTestParticipant.participant_token == body.participant_token)
            .first()
        )
        if existing:
            if existing.campaign_key != CAMPAIGN_KEY or existing.cohort_key != cohort_key:
                raise HTTPException(status_code=403, detail="이 링크에서 발급된 참여 토큰이 아닙니다.")
            return _assignment_payload(existing)

    if not _eligible(body):
        return {"eligible": False, "reason": "이번 검증의 사전 모집 조건과 일치하지 않습니다."}

    row = models.MessageTestParticipant(
        participant_token=secrets.token_urlsafe(32),
        campaign_key=CAMPAIGN_KEY,
        cohort_key=cohort_key,
        variant=_assign_variant(db, cohort_key),
        industry=body.industry.strip()[:40],
        staff_count=body.staff_count,
        directly_handles_bids=body.directly_handles_bids,
        monthly_notice_reviews=body.monthly_notice_reviews,
    )
    db.add(row)
    db.flush()
    db.add(models.GrowthEvent(
        event_name="qualified_visit",
        dedupe_key=f"message-qualified:{row.participant_token}",
        anonymous_id=row.participant_token,
        utm_source="permissioned_message_test",
        utm_medium="self_service",
        utm_campaign=CAMPAIGN_KEY,
        utm_content=f"message_{row.variant.lower()}",
        event_metadata_json={"cohort_key": cohort_key, "variant": row.variant},
    ))
    db.commit()
    db.refresh(row)
    return _assignment_payload(row)


@router.post("/responses")
@limiter.limit("12/hour")
def submit_response(
    request: Request,
    body: ResponseRequest,
    db: Session = Depends(get_db),
):
    cohort_key = _cohort_for(body.access_key)
    row = (
        db.query(models.MessageTestParticipant)
        .filter(models.MessageTestParticipant.participant_token == body.participant_token)
        .first()
    )
    if not row or row.campaign_key != CAMPAIGN_KEY or row.cohort_key != cohort_key:
        raise HTTPException(status_code=404, detail="참여 정보를 찾을 수 없습니다.")
    if row.submitted_at is not None:
        return {"accepted": True, "already_submitted": True}

    # exposure_ms는 브라우저가 보내는 보조 신호라 임의 조작할 수 있다. 서버가 발급한
    # assigned_at과 현재 시각도 함께 확인해 5초 화면을 즉시 건너뛰는 응답을 막는다.
    assigned_at = row.assigned_at
    if assigned_at.tzinfo is None:
        assigned_at = assigned_at.replace(tzinfo=timezone.utc)
    server_elapsed_ms = (datetime.now(timezone.utc) - assigned_at).total_seconds() * 1000
    if body.exposure_ms < 4500 or server_elapsed_ms < 4500:
        raise HTTPException(status_code=400, detail="메시지를 모두 본 뒤 답변해 주세요.")

    coding = code_response(
        body.service_understanding,
        body.usage_moment,
        body.checked_items,
    )
    # SELECT 뒤 동시에 들어온 두 응답이 서로 덮어쓰지 않도록 제출 전용
    # compare-and-set UPDATE를 쓴다. PostgreSQL에서는 먼저 갱신한 transaction이
    # commit된 뒤 두 번째 UPDATE의 WHERE가 다시 평가되어 rowcount=0이 된다.
    updated = (
        db.query(models.MessageTestParticipant)
        .filter(
            models.MessageTestParticipant.id == row.id,
            models.MessageTestParticipant.submitted_at.is_(None),
        )
        .update(
            {
                models.MessageTestParticipant.exposure_ms: body.exposure_ms,
                models.MessageTestParticipant.service_understanding: body.service_understanding.strip(),
                models.MessageTestParticipant.usage_moment: body.usage_moment.strip(),
                models.MessageTestParticipant.checked_items: body.checked_items.strip(),
                models.MessageTestParticipant.trust_score: body.trust_score,
                models.MessageTestParticipant.relevance_score: body.relevance_score,
                models.MessageTestParticipant.coding_json: coding,
                models.MessageTestParticipant.codes_hit: coding["codes_hit"],
                models.MessageTestParticipant.prediction_misunderstood: coding[
                    "prediction_misunderstood"
                ],
                models.MessageTestParticipant.submitted_at: datetime.now(timezone.utc),
            },
            synchronize_session=False,
        )
    )
    if updated == 0:
        db.rollback()
        return {"accepted": True, "already_submitted": True}
    db.commit()
    return {"accepted": True, "already_submitted": False}


def summarize_rows(rows: list[models.MessageTestParticipant]) -> dict:
    submitted = [row for row in rows if row.submitted_at is not None]
    trust_scores = [row.trust_score for row in submitted if row.trust_score is not None]
    understood = sum(1 for row in submitted if (row.codes_hit or 0) >= 3)
    misunderstood = sum(1 for row in submitted if row.prediction_misunderstood)
    trust_median = float(median(trust_scores)) if trust_scores else None
    enough_sample = len(submitted) >= 10
    understood_required = ceil(len(submitted) * 0.7)
    passed = bool(
        enough_sample
        and understood >= understood_required
        and trust_median is not None
        and trust_median >= 4
        and misunderstood < 2
    )
    return {
        "assigned": len(rows),
        "submitted": len(submitted),
        "understood_3_of_4": understood,
        "trust_median": trust_median,
        "prediction_misunderstood": misunderstood,
        "enough_sample": enough_sample,
        "passed_gate": passed,
    }
