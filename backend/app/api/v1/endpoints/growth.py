"""Creative 단위 활성화 퍼널 이벤트.

웹의 무료 가치·설치 클릭은 익명 first-touch와 함께 받고, 핵심 활성화인
``notice_check_completed``는 로그인 사용자·설정된 Extension Origin·실제 공고
context의 1회용 receipt를 함께 검증해 받는다. receipt는 실제 공고와 재생 방지를
보강하지만 Chrome 실행 자체를 attestation하지는 않는다. 같은 공고 새로고침은
서버 dedupe key로 한 번만 센다.
"""

from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import (
    InvalidNoticeCheckReceipt,
    get_current_user,
    get_current_user_optional,
    verify_notice_check_receipt,
)
from app.db import models
from app.db.session import get_db


router = APIRouter()
PUBLIC_EVENTS = frozenset({"free_value_completed", "chrome_install_clicked"})
_BID_NO_RE = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$")


class GrowthEventRequest(BaseModel):
    event_name: str = Field(min_length=1, max_length=60)
    event_id: str = Field(min_length=16, max_length=80)
    anonymous_id: str = Field(min_length=16, max_length=80)
    creative_id: str | None = Field(default=None, min_length=36, max_length=36)
    utm_source: str | None = Field(default=None, max_length=120)
    utm_medium: str | None = Field(default=None, max_length=120)
    utm_campaign: str | None = Field(default=None, max_length=160)
    utm_content: str | None = Field(default=None, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NoticeCheckRequest(BaseModel):
    bid_no: str = Field(min_length=3, max_length=100)
    receipt: str = Field(min_length=80, max_length=2048)
    creative_id: str | None = Field(default=None, min_length=36, max_length=36)
    event_id: str | None = Field(default=None, min_length=16, max_length=80)

    @field_validator("bid_no")
    @classmethod
    def validate_bid_no(cls, value: str) -> str:
        value = value.strip()
        if not _BID_NO_RE.fullmatch(value):
            raise ValueError("공고번호 형식이 올바르지 않습니다.")
        return value


def _known_creative(db: Session, creative_id: str | None) -> str | None:
    if creative_id is None:
        return None
    exists = (
        db.query(models.CreativeBrief.id)
        .filter(
            models.CreativeBrief.id == creative_id,
            models.CreativeBrief.status.in_(("APPROVED", "PUBLISHED")),
        )
        .first()
    )
    if not exists:
        raise HTTPException(status_code=400, detail="게시 승인되지 않은 creative_id입니다.")
    return creative_id


def _bounded_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    try:
        encoded = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="metadata는 JSON 형식이어야 합니다.") from exc
    if len(encoded.encode("utf-8")) > 4096:
        raise HTTPException(status_code=400, detail="metadata가 너무 큽니다.")
    return metadata


def _canonical_notice_bid_no(db: Session, bid_no: str) -> str | None:
    """DB 정본 공고번호를 돌려준다.

    나라장터 화면 경로에는 차수(`-000`)가 빠진 base 번호만 들어오는 경우가 있다.
    정확 일치를 우선하고, 없을 때만 같은 base의 차수 공고를 찾는다. 입력은 위
    validator가 영문·숫자·하이픈으로 제한하므로 LIKE wildcard 주입도 불가능하다.
    """
    exact = db.query(models.Notice.bid_no).filter(models.Notice.bid_no == bid_no).first()
    if exact is not None:
        return str(exact[0])
    prefixed = (
        db.query(models.Notice.bid_no)
        .filter(models.Notice.bid_no.like(f"{bid_no}-%"))
        .order_by(models.Notice.bid_no)
        .first()
    )
    return str(prefixed[0]) if prefixed is not None else None


def _receipt_dedupe_key(nonce: str) -> str:
    """Hash the opaque nonce so the one-time ledger never stores receipt material."""
    return f"notice-receipt:{hashlib.sha256(nonce.encode('ascii')).hexdigest()}"


def _receipt_consumption_row(
    *,
    user_id: int,
    bid_no: str,
    dedupe_key: str,
    occurred_at: datetime,
) -> models.GrowthEvent:
    return models.GrowthEvent(
        event_name="notice_check_receipt_consumed",
        dedupe_key=dedupe_key,
        user_id=user_id,
        bid_no=bid_no,
        event_metadata_json={"purpose": "notice_check_activation"},
        occurred_at=occurred_at,
    )


@router.post("/events", status_code=202)
@limiter.limit("60/hour")
def record_web_event(
    request: Request,
    body: GrowthEventRequest,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(get_current_user_optional),
):
    if body.event_name not in PUBLIC_EVENTS:
        raise HTTPException(status_code=400, detail="허용되지 않은 웹 이벤트입니다.")
    creative_id = _known_creative(db, body.creative_id)
    row = models.GrowthEvent(
        event_name=body.event_name,
        dedupe_key=f"web:{body.event_id}",
        anonymous_id=body.anonymous_id,
        user_id=current_user.id if current_user else None,
        creative_id=creative_id,
        utm_source=body.utm_source,
        utm_medium=body.utm_medium,
        utm_campaign=body.utm_campaign,
        utm_content=body.utm_content,
        event_metadata_json=_bounded_metadata(body.metadata),
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"accepted": True, "duplicate": True}
    return {"accepted": True, "duplicate": False}


@router.post("/extension/notice-check", status_code=202)
@limiter.limit("120/hour")
def record_extension_notice_check(
    request: Request,
    body: NoticeCheckRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    expected_origin = f"chrome-extension://{settings.CHROME_EXTENSION_ID}"
    if request.headers.get("origin") != expected_origin:
        raise HTTPException(status_code=403, detail="BidEasy Chrome 익스텐션 요청만 허용됩니다.")
    current_user_id = current_user.id

    bid_no = _canonical_notice_bid_no(db, body.bid_no)
    if bid_no is None:
        raise HTTPException(status_code=400, detail="BidEasy가 확인한 실제 공고번호가 아닙니다.")

    try:
        receipt_nonce = verify_notice_check_receipt(
            body.receipt,
            expected_user_id=current_user_id,
            expected_bid_no=bid_no,
        )
    except InvalidNoticeCheckReceipt as exc:
        raise HTTPException(
            status_code=403,
            detail="공고 확인 증표가 유효하지 않거나 만료되었습니다.",
        ) from exc

    receipt_key = _receipt_dedupe_key(receipt_nonce)
    receipt_consumed = (
        db.query(models.GrowthEvent.id)
        .filter(models.GrowthEvent.dedupe_key == receipt_key)
        .first()
    )
    if receipt_consumed is not None:
        raise HTTPException(status_code=409, detail="이미 사용한 공고 확인 증표입니다.")

    # 캠페인 winner 지표에는 서버가 가입 시 확정한 first-touch만 사용한다. 가입 귀속이
    # 없는 기존 사용자의 클라이언트 creative_id는 서명된 증거가 아니므로 무시한다.
    # 가입 후 brief가 STALE이 되어도 당시의 실제 first-touch ID는 역사적 귀속으로 보존한다.
    creative_id = current_user.signup_creative_id

    dedupe_key = f"notice-check:{current_user_id}:{bid_no}"
    existing = (
        db.query(models.GrowthEvent.id)
        .filter(models.GrowthEvent.dedupe_key == dedupe_key)
        .first()
    )
    now = datetime.now(timezone.utc)
    if existing:
        db.add(
            _receipt_consumption_row(
                user_id=current_user_id,
                bid_no=bid_no,
                dedupe_key=receipt_key,
                occurred_at=now,
            )
        )
        # 과거 이벤트가 이미 있는데 활성화 시각만 비어 있는 데이터도 복구한다.
        if current_user.first_activation_at is None:
            current_user.first_activation_at = now
            db.add(current_user)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="이미 사용한 공고 확인 증표입니다.") from exc
        return {"accepted": True, "duplicate": True}

    db.add(
        _receipt_consumption_row(
            user_id=current_user_id,
            bid_no=bid_no,
            dedupe_key=receipt_key,
            occurred_at=now,
        )
    )
    row = models.GrowthEvent(
        event_name="notice_check_completed",
        dedupe_key=dedupe_key,
        user_id=current_user_id,
        creative_id=creative_id,
        bid_no=bid_no,
        utm_source=current_user.signup_source,
        utm_medium=current_user.signup_medium,
        utm_campaign=current_user.signup_campaign,
        utm_content=current_user.signup_content,
        event_metadata_json={"client": "chrome_extension"},
        occurred_at=now,
    )
    db.add(row)
    try:
        if current_user.first_activation_at is None:
            current_user.first_activation_at = now
            db.add(current_user)
        db.commit()
    except IntegrityError:
        # 같은 receipt의 동시 재생이면 다른 transaction이 consumption row를 이미
        # 기록했다. 서로 다른 receipt가 같은 공고 활성화를 경합한 경우에만 이번
        # receipt를 새 transaction에서 소비하고 duplicate로 응답한다.
        db.rollback()
        if (
            db.query(models.GrowthEvent.id)
            .filter(models.GrowthEvent.dedupe_key == receipt_key)
            .first()
            is not None
        ):
            raise HTTPException(status_code=409, detail="이미 사용한 공고 확인 증표입니다.")

        activation_exists = (
            db.query(models.GrowthEvent.id)
            .filter(models.GrowthEvent.dedupe_key == dedupe_key)
            .first()
        )
        if activation_exists is None:
            raise HTTPException(status_code=409, detail="활성화 이벤트가 이미 처리 중입니다.")

        current_user = db.query(models.User).filter(models.User.id == current_user_id).first()
        if current_user is not None and current_user.first_activation_at is None:
            current_user.first_activation_at = datetime.now(timezone.utc)
            db.add(current_user)
        db.add(
            _receipt_consumption_row(
                user_id=current_user_id,
                bid_no=bid_no,
                dedupe_key=receipt_key,
                occurred_at=datetime.now(timezone.utc),
            )
        )
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="이미 사용한 공고 확인 증표입니다.") from exc
        return {"accepted": True, "duplicate": True}
    return {"accepted": True, "duplicate": False}
