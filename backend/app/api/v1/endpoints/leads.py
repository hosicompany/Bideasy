"""무료 자격 진단 리드 마그넷 — 비로그인 진단 + 리드 캡처.

리드 확보 전략의 진입 도구(docs/LEAD_ACQUISITION.md). 두 단계:
  1) POST /leads/diagnose — 로그인·연락처 없이 업종·지역·면허를 받아 활성 공고를
     QualificationChecker 로 필터, "넣을 수 있는 공고 N건 + 상위 3건 미리보기" 즉시 반환.
  2) POST /leads/capture — 연락처(이메일/휴대폰)를 남기면 리드로 저장 + 전체 목록 잠금해제.

진단 입력값이 곧 비치헤드 검증 마이크로설문(업종·지역). 발송 인프라(SES/알림톡) 없이도
캡처는 동작 — 육성은 nurture_channel 로 후속 pluggable. 공개 엔드포인트라 IP 레이트리밋.
"""
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.cache import _get_redis, cache_key
from app.core.client_meta import client_ip as _client_ip
from app.core.config import settings
from app.core.logging import get_logger
from app.db import models
from app.db.session import get_db
from app.services import consent as consent_service
from app.services import lead_matching, nurture

logger = get_logger(__name__)

router = APIRouter()

# 매칭 상한은 lead_matching 이 단일 소스(진단·육성 메일 공용)
_MATCH_LIMIT = lead_matching.MATCH_LIMIT
_PREVIEW_N = 3         # 비로그인 미리보기 공개 건수 (나머지는 연락처로 잠금해제)

# 콜드-DB 워밍: 활성 공고가 0건이면(=일일 크롤 전 콜드 스타트) 실방문자에게
# "매칭 0건"이 오인 표시됨(피드는 크롤O·진단은 DB만 읽음). 1회 크롤로 워밍하되
# 공개 엔드포인트라 크롤 남발/DoS 방지 TTL 락 필수.
_WARM_CRAWL_TTL_SEC = 600      # 워밍 크롤 최소 간격(락 TTL)
_last_warm_crawl_ts: float = 0.0  # Redis 미가용 시 프로세스 로컬 폴백 타임스탬프


# ─────────────────────────── 레이트리밋 (IP 기준) ───────────────────────────
# Redis 미가용(dev/test) 시 폴백용 in-memory 롤링 카운터.
_ip_call_log: dict[str, deque] = defaultdict(deque)


def _rate_limit(bucket: str, ip: str, limit: int, window_sec: int = 3600):
    """IP당 window_sec 내 limit 회 초과 시 429. Redis 1차 + in-memory 폴백."""
    r = _get_redis()
    if r is not None:
        try:
            key = cache_key("lead_rl", bucket, ip)
            n = r.incr(key)
            if n == 1:
                r.expire(key, window_sec)
            if n > limit:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="요청이 잠시 많았어요. 잠시 후 다시 시도해 주세요.",
                )
            return
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"lead rate limit Redis 실패, in-memory 폴백: {e}")

    now = datetime.now()
    cutoff = now - timedelta(seconds=window_sec)
    # 무한 증가 방지: 폴백 진입 시(=Redis 미가용) 키가 일정 수 넘으면 stale 키 스윕.
    # deque 는 popleft 로 비워져도 dict 키 자체는 안 지워지므로 주기적으로 정리.
    if len(_ip_call_log) > 5000:
        for k in [k for k, dq in _ip_call_log.items() if not dq or dq[-1] < cutoff]:
            del _ip_call_log[k]
    log = _ip_call_log[f"{bucket}:{ip}"]
    while log and log[0] < cutoff:
        log.popleft()
    if len(log) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="요청이 잠시 많았어요. 잠시 후 다시 시도해 주세요.",
        )
    log.append(now)


# ─────────────────────────── 스키마 ───────────────────────────
class DiagnoseRequest(BaseModel):
    industry: Optional[str] = None       # 업종(예: 전기공사)
    licenses: Optional[str] = None       # 보유 면허(콤마 구분)
    region: Optional[str] = None         # 사업장 소재지(예: 부산광역시) — 지역제한 판정에 필수
    capacity_cost: Optional[int] = None  # 시공능력평가액(선택, 단위: 억원 — 프론트 입력값 그대로)


class CaptureRequest(DiagnoseRequest):
    email: Optional[str] = None
    phone: Optional[str] = None
    nurture_channel: Optional[str] = None   # kakao | email
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    referrer: Optional[str] = None
    # ── 동의 (정보통신망법 제50조 / 개인정보보호법 제22조) ──
    # privacy_consent 가 None 이면 동의 UI 가 없던 **구버전(캐시된) 페이지**의 제출이다.
    # 캡처 자체는 막지 않되(방문자 이탈 방지) 증적이 없으므로 광고성 발송 대상에서 제외한다.
    privacy_consent: Optional[bool] = None
    marketing_consent: bool = False
    consent_version: Optional[str] = None   # 화면에 표시된 동의 문구 버전


# ─────────────────────────── 매칭 로직 ───────────────────────────
# 자격 판정 자체는 services/lead_matching.py 가 단일 소스다(진단 화면과 육성 메일이
# 같은 기준을 써야 사용자가 우리 판정을 믿는다). 여기 남은 것은 진단 화면 전용
# 관심사인 콜드-DB 워밍뿐.
def _active_pool_is_cold(db: Session) -> bool:
    """활성(마감 전) 실공고가 DB 에 하나도 없으면 True(=콜드 DB)."""
    return (
        db.query(models.Notice.bid_no)
        .filter(~models.Notice.title.like("[Mock]%"))
        .filter(models.Notice.end_date > datetime.now())
        .first()
        is None
    )


def _acquire_warm_lock() -> bool:
    """워밍 크롤 스탬피드/DoS 방지. TTL 내 최초 1회만 True.

    Redis NX(원자적 획득) 1차 → Redis 미가용 시 프로세스 로컬 타임스탬프 폴백.
    """
    r = _get_redis()
    if r is not None:
        try:
            # nx=True: 키가 없을 때만 세팅 → 동시 요청 중 최초 1건만 획득
            return bool(r.set(cache_key("lead_warm_crawl"), "1", nx=True, ex=_WARM_CRAWL_TTL_SEC))
        except Exception as e:
            logger.warning(f"warm-crawl 락 Redis 실패, 폴백: {e}")
    global _last_warm_crawl_ts
    now = datetime.now().timestamp()
    if now - _last_warm_crawl_ts < _WARM_CRAWL_TTL_SEC:
        return False
    _last_warm_crawl_ts = now
    return True


def _warm_db_if_cold(db: Session) -> None:
    """콜드-DB(활성 공고 0건)면 1회 크롤로 워밍 — 실방문자 '0건' 오인 방지.

    운영 환경에서만 실제 크롤(개발·테스트는 시딩으로 대체 → mock 오염·네트워크 방지).
    피드와 동일한 fetch→save 패턴, 크롤 실패는 비치명적(진단은 계속 진행).
    """
    if settings.APP_ENV != "production":
        return
    if not _active_pool_is_cold(db):
        return
    if not _acquire_warm_lock():
        return
    from app.services.crawler import CrawlerService

    try:
        results = CrawlerService.fetch_notices(page=1, size=100)  # 공사/용역/물품 3종(최근 5일)
        if results:
            saved = CrawlerService.save_notices(db, results)
            logger.info(f"lead diagnose 콜드-DB 워밍: {len(results)} fetched, {saved} saved")
    except Exception as e:
        logger.warning(f"lead diagnose 워밍 크롤 실패(비치명적): {e}")


def _match_notices(
    db: Session,
    industry: Optional[str],
    licenses: Optional[str],
    region: Optional[str],
) -> List[models.Notice]:
    """진단용 매칭 — 콜드-DB 워밍 후 lead_matching 에 위임."""
    _warm_db_if_cold(db)  # 콜드-DB면 1회 크롤 워밍(운영 전용·가드) 후 아래 조회
    return lead_matching.match_notices(db, industry, licenses, region)


def _notice_card(n: models.Notice) -> dict:
    return {
        "bid_no": n.bid_no,
        "title": n.title,
        "organization": n.organization,
        "region": n.region,
        "basic_price": n.basic_price,
        "end_date": n.end_date.isoformat() if n.end_date else None,
        "contract_type": n.contract_type,
    }


def _valid_contact(email: Optional[str], phone: Optional[str]) -> bool:
    if email and "@" in email and "." in email.split("@")[-1]:
        return True
    if phone and sum(c.isdigit() for c in phone) >= 9:
        return True
    return False


# ─────────────────────────── 엔드포인트 ───────────────────────────
@router.post("/diagnose")
def diagnose(req: DiagnoseRequest, request: Request, db: Session = Depends(get_db)):
    """무료 자격 진단(비로그인) — 넣을 수 있는 공고 수 + 상위 3건 미리보기.

    연락처 없이 즉시 가치 제공. 전체 목록은 /leads/capture 로 연락처 남기면 잠금해제.
    """
    _rate_limit("diagnose", _client_ip(request), limit=40, window_sec=3600)

    if not (req.industry or req.licenses):
        raise HTTPException(status_code=400, detail="업종 또는 보유 면허를 알려주세요.")
    if not req.region:
        # region 없으면 지역제한 공고가 전부 FAIL 처리돼 오해성 0건이 나옴 → 필수화(프론트와 계약 일치).
        raise HTTPException(status_code=400, detail="사업장 소재지를 선택해 주세요.")

    matched = _match_notices(db, req.industry, req.licenses, req.region)
    total = len(matched)
    preview = [_notice_card(n) for n in matched[:_PREVIEW_N]]
    return {
        "matched_count": total,
        "preview": preview,
        "locked_count": max(0, total - len(preview)),
        "capped": total >= _MATCH_LIMIT,  # True 면 실제로 더 많을 수 있음
    }


@router.get("/consent-texts")
def consent_texts():
    """동의 문구 정본 — 화면 문구·증적의 단일 소스(공개, PII 없음).

    프론트가 표시하는 문구와 서버가 해시로 남기는 문구가 갈라지면 증적이 무의미해진다.
    이 엔드포인트는 감사·검증용 정본 공개 창구다(문구 변경 시 버전이 바뀐다).
    """
    return {
        "privacy": {
            "version": consent_service.CURRENT_VERSION[consent_service.PURPOSE_PRIVACY],
            "text": consent_service.consent_text(consent_service.PURPOSE_PRIVACY),
            "required": True,
        },
        "marketing": {
            "version": consent_service.CURRENT_VERSION[consent_service.PURPOSE_MARKETING],
            "text": consent_service.consent_text(consent_service.PURPOSE_MARKETING),
            "required": False,
        },
    }


@router.post("/capture")
def capture(req: CaptureRequest, request: Request, db: Session = Depends(get_db)):
    """리드 캡처 — 연락처 저장 + 전체 매칭 목록 잠금해제.

    이메일 또는 휴대폰 중 하나는 필수. 진단 입력(업종·지역)은 검증 마이크로설문으로 함께 저장.
    동의(필수: 개인정보 수집·이용 / 선택: 광고성 정보 수신)는 증적과 함께 기록한다 —
    광고성 발송은 `services/consent.can_send_marketing` 을 통과한 리드에게만 나간다.
    """
    _rate_limit("capture", _client_ip(request), limit=15, window_sec=3600)

    if not _valid_contact(req.email, req.phone):
        raise HTTPException(status_code=400, detail="연락받을 이메일 또는 휴대폰 번호를 정확히 입력해 주세요.")
    if not (req.industry or req.licenses):
        raise HTTPException(status_code=400, detail="업종 또는 보유 면허를 알려주세요.")
    if not req.region:
        raise HTTPException(status_code=400, detail="사업장 소재지를 선택해 주세요.")

    # 동의 문구 버전 검증 — 모르는 버전이면 화면 문구와 증적이 어긋난다(캐시된 구버전 페이지).
    if req.consent_version:
        try:
            consent_service.resolve_version(consent_service.PURPOSE_PRIVACY, req.consent_version)
            if req.marketing_consent:
                consent_service.resolve_version(consent_service.PURPOSE_MARKETING, req.consent_version)
        except consent_service.UnknownConsentVersion:
            raise HTTPException(
                status_code=400,
                detail="동의 안내문이 갱신됐어요. 페이지를 새로고침한 뒤 다시 시도해 주세요.",
            )

    # 필수 동의를 명시적으로 거부(False)한 경우만 차단. None 은 구버전 페이지(아래에서 발송 제외).
    if req.privacy_consent is False:
        raise HTTPException(
            status_code=400,
            detail="개인정보 수집·이용에 동의해 주셔야 결과를 보내드릴 수 있어요.",
        )
    has_consent_ui = req.privacy_consent is True
    marketing_ok = bool(req.marketing_consent) and has_consent_ui

    matched = _match_notices(db, req.industry, req.licenses, req.region)

    lead = models.Lead(
        email=(req.email or None),
        phone=(req.phone or None),
        industry=req.industry,
        licenses=req.licenses,
        region=req.region,
        capacity_cost=req.capacity_cost,
        matched_count=len(matched),
        utm_source=req.utm_source,
        utm_medium=req.utm_medium,
        utm_campaign=req.utm_campaign,
        referrer=req.referrer,
        nurture_channel=(req.nurture_channel if req.nurture_channel in ("kakao", "email") else None),
        source="web_diagnose",
    )
    db.add(lead)
    db.flush()  # lead.id 확보 — 증적이 어느 리드의 동의인지 가리켜야 한다

    if has_consent_ui:
        consent_service.grant_privacy(
            db, lead, subject_type="lead", source="web_diagnose",
            version=req.consent_version, request=request,
        )
        if marketing_ok:
            consent_service.grant_marketing(
                db, lead, subject_type="lead", source="web_diagnose",
                channel=(lead.nurture_channel or ("kakao" if req.phone else "email")),
                version=req.consent_version, request=request,
            )
    else:
        # 구버전 페이지 제출 — 동의 증적이 없으므로 광고성 발송 대상에서 자동 제외된다.
        logger.warning("lead capture without consent fields (구버전 페이지 캐시 추정)")

    db.commit()
    db.refresh(lead)

    _send_welcome(db, lead, len(matched))

    return {
        "ok": True,
        "lead_id": lead.id,
        "matched_count": len(matched),
        "marketing_consent": bool(lead.marketing_consent),
        "notices": [_notice_card(n) for n in matched],
    }


def _send_welcome(db: Session, lead: models.Lead, matched_count: int) -> None:
    """진단 직후 웰컴 메일 — best-effort.

    리드는 이미 커밋됐다. 발송이 실패하더라도 **리드 저장과 응답을 되돌리지 않는다** —
    메일 한 통 때문에 어렵게 얻은 연락처를 잃는 것이 훨씬 큰 손해다. 동의·억제 게이트와
    멱등은 nurture 가 책임지므로 여기서 조건을 자체 판단하지 않는다(미동의면 nurture 가
    `skipped/no_consent` 로 남긴다).
    """
    if not lead.email:
        return
    try:
        row = nurture.send_marketing(
            db, lead,
            subject_type="lead",
            template="lead_welcome",
            ctx={
                "region": lead.region,
                "industry": lead.industry,
                "matched_count": matched_count,
            },
            dedupe_key=f"lead_welcome:lead:{lead.id}",
        )
        if row.status in ("sent", "dry_run"):
            lead.nurture_status = "sent"
            db.commit()
    except Exception as e:  # noqa: BLE001 — 캡처 응답을 절대 막지 않는다
        db.rollback()
        logger.warning(f"lead welcome 발송 실패(비치명적) lead={lead.id}: {e}")
