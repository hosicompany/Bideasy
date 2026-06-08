from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.schemas import bid as schemas
from app.services.calculator import CalculatorService
from app.db import models
from app.core.logging import get_logger
from app.core.security import get_current_user

logger = get_logger(__name__)

router = APIRouter()

@router.post("/calculate", response_model=schemas.BidCalculationResponse)
def calculate_bid(request: schemas.BidCalculationRequest):
    """
    Calculate safe bid price based on basic price and rate.
    Applies strict 1-won truncation.
    """
    try:
        contract_type = request.contract_type or "CONSTRUCTION"
        
        final_price = CalculatorService.calculate_safe_bid(request.basic_price, request.rate)
        
        lower_limit_rate = CalculatorService.get_lower_limit_rate(contract_type)
        limit_price = request.basic_price * (lower_limit_rate / 100)
        
        is_safe = final_price >= limit_price
        
        return schemas.BidCalculationResponse(
            original_price=request.basic_price,
            rate=request.rate,
            result_price=final_price,
            is_safe=is_safe,
            warning_message=None if is_safe else f"투찰금액이 낙찰하한선({lower_limit_rate}%) 미만입니다."
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/calculate/detailed", response_model=schemas.DetailedBidCalculationResponse)
def calculate_bid_detailed(request: schemas.BidCalculationRequest):
    """
    상세 투찰가 계산 (Advanced Calculator)
    - 예정가격 범위 (±3%)
    - 낙찰하한선 분석
    - 안전도 레벨 (SAFE/WARNING/DANGER)
    - A값 반영 (고정비용 미적용 보장)
    """
    try:
        contract_type = request.contract_type or "CONSTRUCTION"
        a_value = request.a_value or 0
        
        result = CalculatorService.calculate_detailed_bid(
            basic_price=request.basic_price,
            rate=request.rate,
            contract_type=contract_type,
            a_value=a_value
        )
        
        return schemas.DetailedBidCalculationResponse(
            original_price=result.original_price,
            rate=result.rate,
            result_price=result.result_price,
            estimated_price_min=result.estimated_price_min,
            estimated_price_max=result.estimated_price_max,
            lower_limit_rate=result.lower_limit_rate,
            lower_limit_price=result.lower_limit_price,
            a_value=result.a_value,
            a_value_applied=result.a_value_applied,
            safety_level=result.safety_level.value,
            distance_from_limit=result.distance_from_limit,
            warning_message=result.warning_message,
            result_price_formatted=f"{result.result_price:,}원",
            lower_limit_formatted=f"{result.lower_limit_price:,}원",
            a_value_formatted=f"{result.a_value:,}원" if result.a_value > 0 else None
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/feed", response_model=List[schemas.Notice])
def get_feed(
    keyword: str = None,
    region: str = None,
    category: str = None,        # construction | service | goods | all
    date_from: str = None,       # YYYY-MM-DD
    date_to: str = None,
    price_min: int = None,
    price_max: int = None,
    sort: str = None,            # deadline | newest | price
    exclude_closed: bool = False,
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """공고 피드/검색 (공사/용역/물품 통합) — 누적 DB 검색.

    필터: keyword(제목·기관·지역)·region·category·기간·금액·정렬·마감제외.
    동작: (검색이거나 DB 비었으면) OpenAPI fan-out 으로 캐시 갱신 → 그 결과를
    포함한 **누적 notices 테이블 전체**를 필터 검색. 과거에 캐시된 공고도 함께
    검색돼 재현율↑ (조달청 OpenAPI 가 최근 ~5일만 주는 한계 보완).
    """
    from datetime import datetime
    from sqlalchemy import or_, case
    from app.services.crawler import CrawlerService

    now = datetime.now()
    norm_cat = category if category in ("construction", "service", "goods") else None
    CT_MAP = {"construction": "CONSTRUCTION", "service": "SERVICE", "goods": "GOODS"}
    use_api = bool(keyword or region or norm_cat or date_from or date_to)

    # 1) 캐시 갱신: 신규 검색(page 1) 또는 DB 가 비었을 때만 OpenAPI 호출.
    #    (불필요한 3종 fan-out 반복 방지 — page 2+ 는 누적 DB 만 읽음)
    if page == 1 and (
        use_api
        or db.query(models.Notice.bid_no)
        .filter(~models.Notice.title.like("[Mock]%"))
        .first() is None
    ):
        eff_region, eff_keyword = region, keyword
        if not region and keyword and CrawlerService.is_region_keyword(keyword):
            eff_region, eff_keyword = keyword, None
        try:
            api_results = CrawlerService.fetch_notices(
                page=1, size=100, keyword=eff_keyword, region=eff_region,
                category=norm_cat, date_from=date_from, date_to=date_to,
            )
            if api_results:
                CrawlerService.save_notices(db, api_results)
        except Exception as e:
            logger.warning(f"feed API refresh error (non-fatal): {e}")

    # 2) 누적 notices 테이블에서 필터 검색 (API 신선분 + 과거 캐시 통합)
    q = db.query(models.Notice).filter(~models.Notice.title.like("[Mock]%"))
    if keyword:
        kw = f"%{keyword}%"
        q = q.filter(or_(
            models.Notice.title.ilike(kw),
            models.Notice.organization.ilike(kw),
            models.Notice.region.ilike(kw),
        ))
    if region:
        rg = f"%{region}%"
        q = q.filter(or_(models.Notice.organization.ilike(rg), models.Notice.region.ilike(rg)))
    if norm_cat:
        q = q.filter(models.Notice.contract_type == CT_MAP[norm_cat])
    if price_min is not None:
        q = q.filter(models.Notice.basic_price >= price_min)
    if price_max is not None:
        q = q.filter(models.Notice.basic_price <= price_max)
    if exclude_closed:
        q = q.filter(models.Notice.end_date > now)

    if sort == "price":
        q = q.order_by(models.Notice.basic_price.desc())
    elif sort == "newest":
        q = q.order_by(models.Notice.start_date.desc())
    else:  # deadline (기본): 활성 우선 → 마감 임박순
        if exclude_closed:
            q = q.order_by(models.Notice.end_date.asc())
        else:
            is_active = case(
                (models.Notice.end_date.is_(None), 1),
                (models.Notice.end_date > now, 0),
                else_=1,
            )
            q = q.order_by(is_active, models.Notice.end_date.asc())

    offset = (page - 1) * limit
    return q.offset(offset).limit(limit).all()

@router.post("/crawl")
def trigger_crawl(db: Session = Depends(get_db)):
    """
    Trigger real data crawling manually.
    """
    from app.services.crawler import CrawlerService
    from sqlalchemy import text
    try:
        # Auto-migration for dev: Check if contract_type exists
        try:
            db.execute(text("SELECT contract_type FROM notices LIMIT 1"))
        except Exception:
            logger.info("Auto-migration: Adding contract_type column...")
            db.rollback() # Reset transaction
            db.execute(text("ALTER TABLE notices ADD COLUMN contract_type VARCHAR DEFAULT 'CONSTRUCTION'"))
            db.commit()

        logger.info("Triggering Crawl...")
        notices = CrawlerService.fetch_notices(size=50)
        saved_count = CrawlerService.save_notices(db, notices)
        return {"message": "Crawl Success", "fetched": len(notices), "saved": saved_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── DOM 의존도 축소 리팩터: 공고 컨텍스트 엔드포인트 ────────────────
# 익스텐션이 공고번호만 DOM 에서 확보하면, 본문 필드(제목·가격·기관·마감 등)는
# 여기서 OpenAPI/DB 로 가져온다. A값은 OpenAPI 에 없으므로(판정 C) 반환하지 않음.
#
# 라우트 순서 주의: 정적 경로(/batch-context)를 동적 경로(/{bid_no}/...)보다
# 먼저 선언해야 FastAPI 가 batch-context 를 bid_no 로 오인하지 않는다.

def _notice_to_context(notice: models.Notice, source: str) -> schemas.BidContextResponse:
    """DB Notice → BidContextResponse (A값 제외)."""
    return schemas.BidContextResponse(
        bid_ntce_no=notice.bid_no,
        found=True,
        source=source,
        title=notice.title,
        estimated_price=notice.basic_price,        # crawler 가 presmptPrce → basic_price 로 매핑
        budget_amount=notice.budget_amount,
        organization=notice.organization,
        demand_organization=getattr(notice, "demand_organization", None),
        opening_date=getattr(notice, "opening_date", None)
        or (notice.end_date.isoformat() if notice.end_date else None),
        contract_method=getattr(notice, "contract_method", None),
        bid_method=getattr(notice, "bid_method", None),
        qualification=getattr(notice, "bid_qualification", None),
        region=getattr(notice, "region", None),
        contract_type=getattr(notice, "contract_type", None),
    )


def _normalize_bid_no(raw: str) -> str:
    """공백 제거 + 표시형식(...-000) 통일. DB 는 'bidNtceNo-bidNtceOrd' 로 저장."""
    return (raw or "").replace(" ", "").strip()


def _lookup_notice(db: Session, bid_ntce_no: str) -> Optional[models.Notice]:
    """DB Notice 캐시 조회 — 정확 일치 → prefix(공고번호) 일치 순."""
    norm = _normalize_bid_no(bid_ntce_no)
    # 1) 정확 일치 (bid_no = 'R25...-000')
    notice = db.query(models.Notice).filter(models.Notice.bid_no == norm).first()
    if notice:
        return notice
    # 2) 공고번호만 들어온 경우 prefix 매칭 ('R25...' → 'R25...-000')
    base = norm.split("-")[0]
    if base and base != norm:
        return (
            db.query(models.Notice)
            .filter(models.Notice.bid_no.like(f"{base}-%"))
            .first()
        )
    return (
        db.query(models.Notice)
        .filter(models.Notice.bid_no.like(f"{norm}%"))
        .first()
    )


@router.post("/batch-context", response_model=schemas.BatchContextResponse)
def get_batch_context(
    request: schemas.BatchContextRequest,
    db: Session = Depends(get_db),
):
    """목록 페이지 자격뱃지용 — 공고번호 배열 → 자격매칭 최소 필드 배치 반환.

    DB Notice 캐시 우선 조회 (per-bid OpenAPI 호출은 느리고 500 이슈 있음).
    캐시 미스 → found=false → 익스텐션이 해당 row 만 DOM fallback.

    면허는 OpenAPI 에 전용 필드가 없으므로 title 을 함께 반환 →
    익스텐션이 parseRequirementsFromText(title) 로 면허 복원.
    """
    items: list[schemas.BatchContextItem] = []
    found = 0
    for raw in request.bid_ntce_nos[:200]:  # 과도 요청 방지
        notice = _lookup_notice(db, raw)
        if notice:
            found += 1
            items.append(schemas.BatchContextItem(
                bid_ntce_no=raw,
                found=True,
                title=notice.title,
                region=getattr(notice, "region", None),
                contract_type=getattr(notice, "contract_type", None),
                qualification=getattr(notice, "bid_qualification", None),
            ))
        else:
            items.append(schemas.BatchContextItem(bid_ntce_no=raw, found=False))
    return schemas.BatchContextResponse(
        items=items,
        found_count=found,
        miss_count=len(items) - found,
    )


@router.get("/{bid_no}/context", response_model=schemas.BidContextResponse)
def get_bid_context(bid_no: str, db: Session = Depends(get_db)):
    """단건 공고 컨텍스트 — DB 캐시 우선 → OpenAPI → DB 적재.

    A값은 반환하지 않음 (OpenAPI 부재, 익스텐션 DOM 추출 담당).
    found=false 면 익스텐션이 DOM 추출로 fallback.
    """
    # 1) DB 캐시
    notice = _lookup_notice(db, bid_no)
    if notice:
        return _notice_to_context(notice, source="cache")

    # 2) OpenAPI (fetch_bid_detail_robust) → 정규화 → DB 적재
    from app.services.bid_detail import BidDetailService

    norm = _normalize_bid_no(bid_no)
    base = norm.split("-")[0]
    ord_part = norm.split("-")[1] if "-" in norm else "00"
    try:
        detail = BidDetailService.fetch_bid_detail_robust(base, ord_part)
    except Exception as e:
        logger.warning(f"context fetch_bid_detail_robust error for {bid_no}: {e}")
        detail = None

    if not detail:
        # OpenAPI 도 실패 → 익스텐션 DOM fallback 신호
        return schemas.BidContextResponse(
            bid_ntce_no=bid_no, found=False, source="none",
        )

    raw = detail.get("raw_data", {}) or {}
    # OpenAPI 응답을 Notice 로 적재 (다음 호출부터 캐시 히트)
    try:
        bid_no_full = detail.get("bid_no") or norm
        if not db.query(models.Notice).filter(models.Notice.bid_no == bid_no_full).first():
            db.add(models.Notice(
                bid_no=bid_no_full,
                title=detail.get("title", ""),
                basic_price=float(raw.get("presmptPrce", 0) or 0),
                budget_amount=float(raw.get("asignBdgtAmt", 0) or 0),
                organization=detail.get("organization", ""),
                demand_organization=detail.get("demand_organization", ""),
                contract_method=detail.get("contract_method", ""),
                bid_method=detail.get("bid_method", ""),
                region=raw.get("prtcptLmtRgnNm", ""),
                opening_date=detail.get("opening_date", ""),
                contract_type="CONSTRUCTION",
            ))
            db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"context DB 적재 실패 (non-fatal): {e}")

    return schemas.BidContextResponse(
        bid_ntce_no=bid_no,
        found=True,
        source="api",
        title=detail.get("title"),
        estimated_price=float(raw.get("presmptPrce", 0) or 0) or None,
        budget_amount=float(raw.get("asignBdgtAmt", 0) or 0) or None,
        organization=detail.get("organization"),
        demand_organization=detail.get("demand_organization"),
        opening_date=detail.get("opening_date"),
        contract_method=detail.get("contract_method"),
        bid_method=detail.get("bid_method"),
        qualification=raw.get("bidQlfctRgstDt"),
        region=raw.get("prtcptLmtRgnNm"),
        contract_type="CONSTRUCTION",
    )


@router.post("/{bid_no}/favorite")
def toggle_favorite(
    bid_no: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """관심공고 토글 (사용자별)."""
    existing = (
        db.query(models.Favorite)
        .filter(
            models.Favorite.bid_no == bid_no,
            models.Favorite.user_id == current_user.id,
        )
        .first()
    )
    if existing:
        db.delete(existing)
        db.commit()
        return {"status": "removed", "bid_no": bid_no}
    new_fav = models.Favorite(bid_no=bid_no, user_id=current_user.id)
    db.add(new_fav)
    db.commit()
    return {"status": "added", "bid_no": bid_no}


@router.get("/favorites/list", response_model=List[schemas.Notice])
def get_favorites(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """현재 사용자의 관심공고 목록."""
    return (
        db.query(models.Notice)
        .join(models.Favorite, models.Favorite.bid_no == models.Notice.bid_no)
        .filter(models.Favorite.user_id == current_user.id)
        .order_by(models.Favorite.created_at.desc())
        .all()
    )


@router.get("/{bid_no}/favorite")
def is_favorite(
    bid_no: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """해당 공고가 현재 사용자의 관심공고인지."""
    fav = (
        db.query(models.Favorite.id)
        .filter(
            models.Favorite.bid_no == bid_no,
            models.Favorite.user_id == current_user.id,
        )
        .first()
    )
    return {"favorited": fav is not None}


class AValueReport(BaseModel):
    a_value: int


@router.put("/{bid_no}/a_value")
def report_a_value(
    bid_no: str,
    payload: AValueReport,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """A값 크라우드소스 캐시 (Tier 1).

    익스텐션이 나라장터 DOM 에서 읽은 A값을 보고 → Notice.a_value 에 저장.
    이후 웹 상세/계산기가 이 값을 자동 표시 (OpenAPI 엔 A값 없음).
    A값은 공개 공고정보라 캐시·공유 무방.
    """
    if payload.a_value < 0 or payload.a_value > 100_000_000_000:
        raise HTTPException(status_code=400, detail="유효하지 않은 A값")

    notice = _lookup_notice(db, bid_no)
    if not notice:
        # 캐시에 없으면 OpenAPI 로 적재 시도 후 재조회
        try:
            get_bid_context(bid_no, db)
        except Exception:
            pass
        notice = _lookup_notice(db, bid_no)
    if not notice:
        return {"updated": False, "reason": "notice_not_found", "bid_no": bid_no}

    notice.a_value = int(payload.a_value)
    db.commit()
    logger.info(f"A값 보고: {notice.bid_no} = {payload.a_value} (user={current_user.id})")
    return {"updated": True, "bid_no": notice.bid_no, "a_value": notice.a_value}


@router.get("/{bid_no}/qualification")
def get_qualification(
    bid_no: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """현재 사용자 프로필(면허·지역)로 해당 공고 입찰 자격 판정.

    QualificationChecker 재사용 (AI 분석과 동일 엔진). {status, message, details}.
    """
    from app.services.qualification_checker import QualificationChecker

    notice = _lookup_notice(db, bid_no)
    if not notice:
        try:
            get_bid_context(bid_no, db)
        except Exception:
            pass
        notice = _lookup_notice(db, bid_no)
    if not notice:
        return {"status": "UNKNOWN", "message": "공고 정보를 찾을 수 없습니다.", "details": []}

    check_data = {
        "bidNtceNm": notice.title or "",
        "LmtRegion": getattr(notice, "region", "") or "",
        "bidNtceNo": notice.bid_no,
    }
    return QualificationChecker.check_qualification(check_data, current_user)


@router.get("/{bid_no}/results", response_model=List[schemas.OpeningResult])
def get_opening_results(bid_no: str, db: Session = Depends(get_db)):
    """
    Get Opening Results (Ranking) for a bid.
    """
    from app.services.opening_result import OpeningResultService
    
    # Fetch notice to know contract_type
    notice = db.query(models.Notice).filter(models.Notice.bid_no == bid_no).first()
    contract_type = notice.contract_type if notice else "CONSTRUCTION"
    
    return OpeningResultService.fetch_opening_results(bid_no, contract_type)

