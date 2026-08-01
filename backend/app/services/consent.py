"""수신동의 증적 서비스 — 아웃바운드(SES·알림톡) 발송의 법적 전제.

왜 이 모듈이 발송 코드보다 먼저인가
-----------------------------------
정보통신망법 제50조는 영리목적 광고성 정보 전송에 **명시적 사전 동의**를 요구하고,
분쟁 시 증명책임은 전송자(우리)에게 있다. 즉 "동의를 받았다"가 아니라
**"받았음을 증명할 수 있다"**가 판정 기준이다. 그래서 발송 어댑터를 붙이기 전에
증적 구조를 먼저 세운다.

설계 원칙
---------
1. **상태와 증적을 분리한다.** `Lead/User.marketing_consent` 는 현재 상태(갱신·철회로
   덮어써짐)이고, `consent_records` 는 추가 전용 로그다. 한 행도 수정하지 않는다.
2. **동의한 문구를 특정할 수 있어야 한다.** 버전 문자열 + 본문 sha256 을 함께 남긴다.
   문구를 나중에 바꿔도 "그때 무엇에 동의했는지"가 해시로 고정된다.
3. **구버전 문구도 보존한다.** `CONSENT_TEXTS` 는 버전별 사전이며 과거 버전을 지우지
   않는다. 클라이언트가 보낸 버전의 본문을 그대로 해시한다(화면에 보인 문구 = 증적).
4. **발송 가능 판정을 한 곳에 둔다.** `can_send_marketing()` / `sendable_filter()` 만
   쓰면, 2년 재확인(제50조 제8항)·철회 반영이 자동으로 걸린다. 발송 태스크가
   `marketing_consent == True` 만 보고 조건을 자체 판단하면 사고가 난다.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Request
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.client_meta import client_ip, user_agent
from app.core.logging import get_logger
from app.db import models

logger = get_logger(__name__)

# 동의 후 재확인 주기 — 정보통신망법 제50조 제8항(2년마다 수신동의 여부 확인).
# 초과하면 재확인 전까지 발송 대상에서 자동 제외된다(can_send_marketing).
REVALIDATE_DAYS = 730

# 동의 목적
PURPOSE_PRIVACY = "privacy"      # 개인정보 수집·이용 (필수)
PURPOSE_MARKETING = "marketing"  # 광고성 정보 수신 (선택)

# 증적 행위
ACTION_GRANT = "grant"
ACTION_WITHDRAW = "withdraw"
ACTION_RECONFIRM = "reconfirm"


# ─────────────────────────── 동의 문구 정본 ───────────────────────────
# ⚠️ 여기 본문과 화면(diagnose.html·signup.html)의 문구는 **같아야 한다.**
#    문구를 고치면 반드시 새 버전 키를 추가하고(기존 버전은 삭제 금지) 화면의
#    data-consent-version 도 함께 올린다. tests/test_consent.py 가 드리프트를 잡는다.

_PRIVACY_LEAD_V1 = """[필수] 개인정보 수집·이용 동의
· 수집 항목: 이메일 또는 휴대폰 번호, 업종·보유 면허·사업장 소재지·시공능력평가액(선택)
· 이용 목적: 무료 자격 진단 결과 제공 및 문의 응대
· 보유 기간: 수집일로부터 1년 또는 삭제 요청 시까지
· 동의를 거부하실 수 있으며, 거부 시 진단 결과 전체 목록 제공이 제한됩니다."""

_MARKETING_V1 = """[선택] 광고성 정보 수신 동의
· 전송 내용: 조건에 맞는 신규 공고 알림, 입찰 정보·서비스 소식 등 광고성 정보
· 전송 채널: 이메일(휴대폰을 남기신 경우 카카오 알림톡 포함)
· 철회 방법: 각 메시지의 수신거부 링크 또는 support@bideasy.kr 로 언제든 철회할 수 있습니다.
· 동의를 거부하셔도 진단 결과 확인에는 제한이 없습니다."""

_MARKETING_SIGNUP_V1 = """[선택] 광고성 정보 수신 동의
· 전송 내용: 자격에 맞는 신규 공고 알림, 입찰 정보·서비스 소식 등 광고성 정보
· 전송 채널: 이메일
· 철회 방법: 각 메시지의 수신거부 링크 또는 support@bideasy.kr 로 언제든 철회할 수 있습니다.
· 동의를 거부하셔도 서비스 이용에는 제한이 없습니다(체험·결제 안내 등 거래 관련 안내는 계속 발송됩니다)."""

# purpose → {version: 본문}. 과거 버전은 증적 해석을 위해 영구 보존.
CONSENT_TEXTS: dict[str, dict[str, str]] = {
    PURPOSE_PRIVACY: {"2026-07-30.v1": _PRIVACY_LEAD_V1},
    PURPOSE_MARKETING: {
        "2026-07-30.v1": _MARKETING_V1,
        "2026-07-30.signup.v1": _MARKETING_SIGNUP_V1,
    },
}

# 화면이 기본으로 표시해야 할 최신 버전
CURRENT_VERSION: dict[str, str] = {
    PURPOSE_PRIVACY: "2026-07-30.v1",
    PURPOSE_MARKETING: "2026-07-30.v1",
}
# 회원가입 폼은 리드 폼과 문구가 달라 별도 버전을 쓴다.
SIGNUP_MARKETING_VERSION = "2026-07-30.signup.v1"


class UnknownConsentVersion(ValueError):
    """클라이언트가 서버에 없는 동의 문구 버전을 보냈다(대개 캐시된 구버전 페이지)."""


def _utcnow() -> datetime:
    """DB 비교용 naive UTC(기존 서비스 컨벤션과 일치)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def resolve_version(purpose: str, claimed: Optional[str]) -> str:
    """클라이언트가 보낸 버전을 검증해 확정. 미지정이면 현재 버전."""
    versions = CONSENT_TEXTS.get(purpose) or {}
    if not claimed:
        return CURRENT_VERSION[purpose]
    if claimed not in versions:
        raise UnknownConsentVersion(claimed)
    return claimed


def consent_text(purpose: str, version: Optional[str] = None) -> str:
    """해당 버전의 동의 문구 본문."""
    return CONSENT_TEXTS[purpose][resolve_version(purpose, version)]


def text_hash(purpose: str, version: Optional[str] = None) -> str:
    """동의 문구 본문의 sha256 — 사후 문구 변경 탐지용 지문."""
    return hashlib.sha256(consent_text(purpose, version).encode("utf-8")).hexdigest()


# ─────────────────────────── 증적 기록 ───────────────────────────
def record(
    db: Session,
    *,
    subject_type: str,
    subject_id: Optional[int],
    purpose: str,
    action: str,
    source: str,
    version: Optional[str] = None,
    channel: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    request: Optional[Request] = None,
    ip: Optional[str] = None,
    ua: Optional[str] = None,
    note: Optional[str] = None,
) -> models.ConsentRecord:
    """동의·철회 증적 1행 추가(커밋은 호출부 책임).

    request 를 주면 IP·User-Agent 를 자동 추출한다(명시 ip/ua 가 우선).
    """
    if request is not None:
        ip = ip or client_ip(request)
        ua = ua or user_agent(request)

    ver = resolve_version(purpose, version)
    rec = models.ConsentRecord(
        subject_type=subject_type,
        subject_id=subject_id,
        email=(email or None),
        phone=(phone or None),
        purpose=purpose,
        action=action,
        channel=channel,
        text_version=ver,
        text_hash=text_hash(purpose, ver),
        source=source,
        ip=(ip or None),
        user_agent=(ua[:300] if ua else None),
        note=(note[:200] if note else None),
    )
    db.add(rec)
    return rec


def grant_privacy(
    db: Session,
    subject,
    *,
    subject_type: str,
    source: str,
    version: Optional[str] = None,
    request: Optional[Request] = None,
) -> models.ConsentRecord:
    """개인정보 수집·이용 동의(필수) — 상태 갱신 + 증적."""
    now = _utcnow()
    ver = resolve_version(PURPOSE_PRIVACY, version)
    subject.privacy_consent = True
    subject.privacy_consent_at = now
    subject.consent_text_version = ver
    if request is not None:
        subject.consent_ip = client_ip(request)
        subject.consent_user_agent = user_agent(request)
    return record(
        db,
        subject_type=subject_type,
        subject_id=getattr(subject, "id", None),
        purpose=PURPOSE_PRIVACY,
        action=ACTION_GRANT,
        source=source,
        version=ver,
        email=getattr(subject, "email", None),
        phone=getattr(subject, "phone", None),
        request=request,
    )


def grant_marketing(
    db: Session,
    subject,
    *,
    subject_type: str,
    source: str,
    channel: str = "email",
    version: Optional[str] = None,
    request: Optional[Request] = None,
    confirmed: bool = True,
) -> models.ConsentRecord:
    """광고성 정보 수신 동의(선택) — 상태 갱신 + 증적.

    재동의(철회 후 다시 동의)도 이 함수로 처리한다: withdrawn_at 을 비우고
    동의 시각을 새로 찍되, 철회 증적은 로그에 그대로 남는다.

    `confirmed=False` 는 **더블 옵트인 대기** 상태다. 인증 없는 공개 폼(리드 진단)은
    제출자가 그 주소의 주인이라는 증거가 없다 — 남의 주소를 적어도 우리가 가진 증적은
    제출자의 IP·UA 뿐이다. 그래서 주소 소유자가 확인 링크를 누를 때까지
    `marketing_confirmed_at` 을 비워 두고, `sendable_filter` 가 그 사이 광고 발송을
    막는다(그 컬럼이 NULL 이면 발송 대상이 아니다).
    """
    now = _utcnow()
    ver = resolve_version(PURPOSE_MARKETING, version)
    subject.marketing_consent = True
    subject.marketing_consent_at = now
    subject.marketing_confirmed_at = now if confirmed else None
    subject.marketing_withdrawn_at = None
    subject.consent_text_version = ver
    if request is not None:
        subject.consent_ip = client_ip(request)
        subject.consent_user_agent = user_agent(request)
    return record(
        db,
        subject_type=subject_type,
        subject_id=getattr(subject, "id", None),
        purpose=PURPOSE_MARKETING,
        action=ACTION_GRANT,
        source=source,
        version=ver,
        channel=channel,
        email=getattr(subject, "email", None),
        phone=getattr(subject, "phone", None),
        request=request,
    )


def confirm_marketing(
    db: Session,
    subject,
    *,
    subject_type: str,
    source: str,
    channel: str = "email",
    request: Optional[Request] = None,
) -> Optional[models.ConsentRecord]:
    """더블 옵트인 확인 — 주소 소유자가 확인 링크를 눌렀다.

    이 시점에야 `marketing_confirmed_at` 이 채워져 `sendable_filter` 를 통과한다.
    철회한 사람이 확인 링크를 눌러 되살아나는 일이 없도록, 철회 이력이 있으면
    아무것도 하지 않는다(재동의는 명시적 재신청 경로로만).
    """
    if getattr(subject, "marketing_withdrawn_at", None) is not None:
        return None
    if not getattr(subject, "marketing_consent", False):
        return None

    subject.marketing_confirmed_at = _utcnow()
    return record(
        db,
        subject_type=subject_type,
        subject_id=getattr(subject, "id", None),
        purpose=PURPOSE_MARKETING,
        action=ACTION_RECONFIRM,
        source=source,
        version=getattr(subject, "consent_text_version", None) or None,
        channel=channel,
        email=getattr(subject, "email", None),
        phone=getattr(subject, "phone", None),
        request=request,
        note="더블 옵트인 확인",
    )


def withdraw_marketing(
    db: Session,
    subject,
    *,
    subject_type: str,
    source: str,
    request: Optional[Request] = None,
    note: Optional[str] = None,
) -> models.ConsentRecord:
    """수신거부(철회) — 즉시 발송 대상에서 빠진다. 증적은 남긴다."""
    subject.marketing_consent = False
    subject.marketing_withdrawn_at = _utcnow()
    if hasattr(subject, "nurture_status"):
        # 전환 완료 리드는 상태를 덮어쓰지 않는다(전환 측정 보존).
        if subject.nurture_status != "converted":
            subject.nurture_status = "unsub"
    return record(
        db,
        subject_type=subject_type,
        subject_id=getattr(subject, "id", None),
        purpose=PURPOSE_MARKETING,
        action=ACTION_WITHDRAW,
        source=source,
        version=getattr(subject, "consent_text_version", None) or None,
        email=getattr(subject, "email", None),
        phone=getattr(subject, "phone", None),
        request=request,
        note=note,
    )


# ─────────────────────────── 발송 가능 판정 ───────────────────────────
def can_send_marketing(subject, now: Optional[datetime] = None) -> bool:
    """이 대상에게 지금 광고성 정보를 보내도 되는가.

    발송 코드는 **반드시** 이 함수(또는 sendable_filter)를 통과시킨 대상에게만 보낸다.
    조건: 동의 상태 True · 철회 이력 없음 · 마지막 확인이 2년 이내.
    """
    if not getattr(subject, "marketing_consent", False):
        return False
    if getattr(subject, "marketing_withdrawn_at", None) is not None:
        return False
    # `marketing_confirmed_at` 만 본다 — `marketing_consent_at` 으로 폴백하지 않는다.
    # 폴백을 두면 ① 더블 옵트인 대기 상태(확인 전)가 발송 가능으로 새고
    # ② SQL 판본(sendable_filter)은 이 컬럼을 필수로 요구하므로 단건 판정과 갈라진다.
    # 판정이 두 갈래면 언젠가 반드시 위법 발송 쪽으로 갈라진다.
    confirmed = getattr(subject, "marketing_confirmed_at", None)
    if confirmed is None:
        return False  # 동의 플래그만 있고 확인 증적이 없으면 보내지 않는다
    if confirmed.tzinfo is not None:
        confirmed = confirmed.astimezone(timezone.utc).replace(tzinfo=None)
    return (now or _utcnow()) - confirmed <= timedelta(days=REVALIDATE_DAYS)


def sendable_filter(model, now: Optional[datetime] = None):
    """`can_send_marketing` 의 SQL 판본 — 발송 대상 조회에 그대로 얹는다.

    사용: db.query(models.Lead).filter(consent.sendable_filter(models.Lead))
    """
    cutoff = (now or _utcnow()) - timedelta(days=REVALIDATE_DAYS)
    return and_(
        model.marketing_consent.is_(True),
        model.marketing_withdrawn_at.is_(None),
        model.marketing_confirmed_at.isnot(None),
        model.marketing_confirmed_at >= cutoff,
    )
