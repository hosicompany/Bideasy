"""무료 자격 진단 리드 마그넷 — 비로그인 진단 + 리드 캡처.

리드 확보 전략의 진입 도구(docs/LEAD_ACQUISITION.md). 두 단계:
  1) POST /leads/diagnose — 로그인·연락처 없이 업종·지역·면허를 받아 활성 공고를
     QualificationChecker 로 필터, "넣을 수 있는 공고 N건 + 상위 3건 미리보기" 즉시 반환.
  2) POST /leads/capture — 연락처(이메일/휴대폰)를 남기면 리드로 저장 + 전체 목록 잠금해제.

진단 입력값이 곧 비치헤드 검증 마이크로설문(업종·지역). 발송 인프라(SES/알림톡) 없이도
캡처는 동작 — 육성은 nurture_channel 로 후속 pluggable. 공개 엔드포인트라 IP 레이트리밋.
"""
import unicodedata
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.cache import _get_redis, cache_key
from app.core.client_meta import client_ip as _client_ip
from app.core.config import settings
from app.core.logging import get_logger
from app.core.signed_token import InvalidSignedToken, parse_token
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


# 자유 텍스트 필드의 저장 상한 — 컬럼 길이(region 100 / industry 60 / licenses 255)를
# 넘으면 Postgres 는 DataError 를 던진다(SQLite 는 조용히 통과해 테스트가 못 잡는다).
_TEXT_LIMITS = {"industry": 60, "licenses": 255, "region": 100}


def _clean_text(value: Optional[str], limit: int) -> Optional[str]:
    """공개 폼에서 들어온 자유 텍스트를 저장·발송에 안전한 형태로 정규화.

    제어문자(특히 개행)를 지우는 이유는 이 값이 나중에 **메일 제목**에 들어가기 때문이다.
    제목에 개행이 섞이면 헤더 인젝션 방어가 예외를 던지고, 그 리드는 매주 같은 지점에서
    발송을 실패시킨다. 입력 시점에 끊는 것이 가장 싸다.
    """
    if value is None:
        return None
    # 제어문자는 삭제가 아니라 공백으로 치환한다 — 지워버리면 "부산광역시\n경상남도" 가
    # "부산광역시경상남도" 로 붙어 사용자가 쓴 적 없는 값이 저장된다.
    cleaned = "".join(" " if unicodedata.category(ch)[0] == "C" else ch for ch in value)
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned[:limit] or None


def _normalize_email(email: Optional[str]) -> Optional[str]:
    """발송 주체 식별용 정규화 — 대소문자·공백 차이로 같은 사람이 갈라지지 않게."""
    if not email:
        return None
    return email.strip().lower() or None


def _recipient_key(email: Optional[str]) -> str:
    """멱등 키의 주체 = 수신자(이메일).

    `lead.id` 를 쓰면 같은 사람이 재진단할 때마다 새 Lead 행이 생겨 키가 갈라지고,
    한 사람에게 같은 메일이 여러 통 나간다. 실제로 중복을 체감하는 주체는 행이 아니라
    **받는 사람**이므로 키도 거기에 맞춘다.
    """
    import hashlib

    return hashlib.sha1((_normalize_email(email) or "").encode("utf-8")).hexdigest()[:16]


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

    # 자유 텍스트는 저장 전에 정규화한다 — 이 값들이 나중에 메일 제목에 들어간다.
    industry = _clean_text(req.industry, _TEXT_LIMITS["industry"])
    licenses = _clean_text(req.licenses, _TEXT_LIMITS["licenses"])
    region = _clean_text(req.region, _TEXT_LIMITS["region"])

    matched = _match_notices(db, industry, licenses, region)

    lead = models.Lead(
        email=_normalize_email(req.email),
        phone=(req.phone or None),
        industry=industry,
        licenses=licenses,
        region=region,
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
            # confirmed=False — 이 폼은 인증이 없어 제출자가 그 주소의 주인이라는 증거가
            # 없다. 주소 소유자가 확인 링크를 누르기 전까지 sendable_filter 가 광고를 막는다.
            consent_service.grant_marketing(
                db, lead, subject_type="lead", source="web_diagnose",
                channel=(lead.nurture_channel or ("kakao" if req.phone else "email")),
                version=req.consent_version, request=request,
                confirmed=False,
            )
    else:
        # 구버전 페이지 제출 — 동의 증적이 없으므로 광고성 발송 대상에서 자동 제외된다.
        logger.warning("lead capture without consent fields (구버전 페이지 캐시 추정)")

    db.commit()
    db.refresh(lead)

    if marketing_ok:
        _send_optin_confirm(db, lead)

    return {
        "ok": True,
        "lead_id": lead.id,
        "matched_count": len(matched),
        "marketing_consent": bool(lead.marketing_consent),
        "confirm_pending": bool(marketing_ok),   # 확인 메일을 눌러야 알림이 시작된다
        "notices": [_notice_card(n) for n in matched],
    }


# ─────────────────────────── 더블 옵트인 ───────────────────────────
OPTIN_PURPOSE = "optin"


def optin_url(lead_id: int) -> str:
    from app.core.signed_token import make_token

    token = make_token(OPTIN_PURPOSE, "lead", lead_id)
    return f"{settings.PUBLIC_WEB_URL}/optin?t={token}"


def _send_optin_confirm(db: Session, lead: models.Lead) -> None:
    """수신 신청 확인 메일 — best-effort.

    리드는 이미 커밋됐다. 발송이 실패해도 **리드 저장과 응답을 되돌리지 않는다** —
    메일 한 통 때문에 어렵게 얻은 연락처를 잃는 것이 훨씬 큰 손해다.

    이 메일은 광고가 아니라 거래성(확인 요청)이라 미확인 주소에도 보낼 수 있다. 대신
    본문에 광고를 담지 않는다 — 담는 순간 미확인 주소로 보낸 광고물이 된다.
    """
    if not lead.email:
        return
    try:
        nurture.send_transactional(
            db, lead,
            subject_type="lead",
            template="lead_optin_confirm",
            ctx={
                "confirm_url": optin_url(lead.id),
                "region": lead.region,
                "industry": lead.industry,
            },
            dedupe_key=f"lead_optin_confirm:email:{_recipient_key(lead.email)}",
        )
    except Exception as e:  # noqa: BLE001 — 캡처 응답을 절대 막지 않는다
        db.rollback()
        logger.warning(f"lead optin 확인메일 발송 실패(비치명적) lead={lead.id}: {e}")


def _resolve_optin(db: Session, token: Optional[str]) -> models.Lead:
    try:
        subject_type, subject_id = parse_token(OPTIN_PURPOSE, token)
    except InvalidSignedToken:
        raise HTTPException(status_code=400, detail="링크가 올바르지 않아요. 메일의 링크를 다시 눌러 주세요.")
    if subject_type != "lead":
        raise HTTPException(status_code=400, detail="링크가 올바르지 않아요.")
    lead = db.get(models.Lead, subject_id)
    if lead is None:
        raise HTTPException(status_code=400, detail="링크가 만료됐어요. 진단을 다시 받아 주세요.")
    return lead


@router.get("/optin/status")
def optin_status(token: str = Query(...), db: Session = Depends(get_db)):
    """확인 전 조회 — 상태를 바꾸지 않는다.

    GET 으로 확정하지 않는 이유는 수신거부와 같다: 메일 서버·보안 스캐너가 링크를 미리
    열어보면 사용자 의사와 무관하게 확인 처리돼 더블 옵트인이 무의미해진다.
    """
    lead = _resolve_optin(db, token)
    return {
        "valid": True,
        "confirmed": consent_service.can_send_marketing(lead),
        "region": lead.region,
        "industry": lead.industry,
    }


@router.post("/optin")
def optin_confirm(
    request: Request,
    token: Optional[str] = Query(None),
    body_token: Optional[str] = Body(None, embed=True, alias="token"),
    db: Session = Depends(get_db),
):
    """수신 신청 확인 — 이 시점부터 광고 발송 대상이 된다(멱등)."""
    lead = _resolve_optin(db, token or body_token)

    already = consent_service.can_send_marketing(lead)
    if not already:
        rec = consent_service.confirm_marketing(
            db, lead, subject_type="lead", source="email_optin", request=request,
        )
        if rec is None:
            # 철회했거나 동의 자체가 없는 리드 — 확인으로 되살리지 않는다.
            raise HTTPException(status_code=400, detail="수신 신청 내역이 없어요. 진단을 다시 받아 주세요.")
        db.commit()
        db.refresh(lead)
        logger.info("lead optin confirmed: lead=%s", lead.id)
        _send_welcome(db, lead)

    return {"ok": True, "already": already}


def _send_welcome(db: Session, lead: models.Lead) -> None:
    """확인을 마친 리드에게 보내는 웰컴(광고) — best-effort.

    멱등 키의 주체는 `lead.id` 가 아니라 **수신자**다. 같은 사람이 재진단하면 Lead 행이
    새로 생기는데, 행 기준으로 키를 잡으면 같은 사람에게 같은 메일이 여러 통 나간다.
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
                "matched_count": lead.matched_count or 0,
                # 진단 화면이 `capped` 로 "더 있을 수 있다"고 말한 것과 같은 기준.
                # 캡에 걸린 값을 딱 떨어지게 말하면 사실과 다른 수를 말하게 된다.
                "capped": (lead.matched_count or 0) >= _MATCH_LIMIT,
            },
            dedupe_key=f"lead_welcome:email:{_recipient_key(lead.email)}",
        )
        if row.status in ("sent", "dry_run") and lead.nurture_status != "converted":
            lead.nurture_status = "sent"
            db.commit()
    except Exception as e:  # noqa: BLE001 — 확인 응답을 막지 않는다
        db.rollback()
        logger.warning(f"lead welcome 발송 실패(비치명적) lead={lead.id}: {e}")
