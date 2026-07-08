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
from types import SimpleNamespace
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.cache import _get_redis, cache_key
from app.core.logging import get_logger
from app.db import models
from app.db.session import get_db
from app.services.qualification_checker import QualificationChecker

logger = get_logger(__name__)

router = APIRouter()

# 진단 스캔·반환 상한 (성능 보호)
_SCAN_LIMIT = 500      # 자격 판정할 후보 공고 최대 스캔 수
_MATCH_LIMIT = 50      # 반환할 매칭 공고 최대 수
_PREVIEW_N = 3         # 비로그인 미리보기 공개 건수 (나머지는 연락처로 잠금해제)

# 업종·면허 텍스트에서 대표 면허 루트 키워드 추출용
# (QualificationChecker 가 공고 제목에서 인식하는 키워드와 정합)
_LICENSE_ROOTS = ["전기", "정보통신", "통신", "소방", "건축", "토목"]


# ─────────────────────────── 레이트리밋 (IP 기준) ───────────────────────────
# Redis 미가용(dev/test) 시 폴백용 in-memory 롤링 카운터.
_ip_call_log: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    """프록시(nginx) 뒤 실 IP.

    ⚠️ XFF 의 첫 요소는 클라이언트가 위조할 수 있다. nginx 는
    `$proxy_add_x_forwarded_for` 로 실 IP 를 **맨 뒤**에 append 하므로,
    신뢰 프록시(1단)가 붙인 마지막 요소를 실 클라이언트 IP 로 사용한다.
    (첫 요소를 쓰면 XFF 스푸핑으로 레이트리밋이 통째로 우회됨)
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


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


# ─────────────────────────── 매칭 로직 ───────────────────────────
def _detect_root(*texts: Optional[str]) -> Optional[str]:
    """업종·면허 문자열에서 대표 면허 루트 키워드 1개 추출(없으면 None)."""
    blob = " ".join(t for t in texts if t)
    for root in _LICENSE_ROOTS:
        if root in blob:
            return root
    return None


def _match_notices(
    db: Session,
    industry: Optional[str],
    licenses: Optional[str],
    region: Optional[str],
) -> List[models.Notice]:
    """활성 공고를 QualificationChecker 로 필터해 자격 PASS 공고만 반환.

    로그인 없이 동작하도록 user 자리에 가상 프로필(location/licenses 속성만)을 넣는다.
    업종 루트 키워드가 있으면 후보를 그 공종으로 좁혀 '내 공종의 넣을 수 있는 공고'로 정밀화.
    """
    pseudo = SimpleNamespace(location=(region or ""), licenses=(licenses or industry or ""))

    q = db.query(models.Notice).filter(~models.Notice.title.like("[Mock]%"))
    q = q.filter(models.Notice.end_date > datetime.now())  # 활성(마감 전)만

    root = _detect_root(industry, licenses)
    if root:
        q = q.filter(models.Notice.title.ilike(f"%{root}%"))

    candidates = q.order_by(models.Notice.end_date.asc()).limit(_SCAN_LIMIT).all()

    matched: List[models.Notice] = []
    for n in candidates:
        notice_dict = {"bidNtceNm": n.title or "", "LmtRegion": n.region or ""}
        res = QualificationChecker.check_qualification(notice_dict, pseudo)
        if res.get("status") == "PASS":
            matched.append(n)
            if len(matched) >= _MATCH_LIMIT:
                break
    return matched


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


@router.post("/capture")
def capture(req: CaptureRequest, request: Request, db: Session = Depends(get_db)):
    """리드 캡처 — 연락처 저장 + 전체 매칭 목록 잠금해제.

    이메일 또는 휴대폰 중 하나는 필수. 진단 입력(업종·지역)은 검증 마이크로설문으로 함께 저장.
    """
    _rate_limit("capture", _client_ip(request), limit=15, window_sec=3600)

    if not _valid_contact(req.email, req.phone):
        raise HTTPException(status_code=400, detail="연락받을 이메일 또는 휴대폰 번호를 정확히 입력해 주세요.")
    if not (req.industry or req.licenses):
        raise HTTPException(status_code=400, detail="업종 또는 보유 면허를 알려주세요.")
    if not req.region:
        raise HTTPException(status_code=400, detail="사업장 소재지를 선택해 주세요.")

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
    db.commit()
    db.refresh(lead)

    return {
        "ok": True,
        "lead_id": lead.id,
        "matched_count": len(matched),
        "notices": [_notice_card(n) for n in matched],
    }
