from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.schemas import bid as schemas
from app.services.calculator import CalculatorService
from app.db import models
from app.core.logging import get_logger

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
    """공고 피드/검색 (공사/용역/물품 통합).

    필터: keyword(제목)·region(기관)·category·기간·금액·정렬·마감제외.
    검색 조건이 있으면 OpenAPI fan-out, 없으면 DB 기본 피드.
    """
    from datetime import datetime
    from app.services.crawler import CrawlerService

    now = datetime.now()
    norm_cat = category if category in ("construction", "service", "goods") else None

    def _post_filter(items: list) -> list:
        """공통 post-filter: 금액·마감제외·정렬. items 는 dict 또는 ORM Notice."""
        def g(it, attr):
            return it.get(attr) if isinstance(it, dict) else getattr(it, attr, None)

        out = items
        if price_min is not None:
            out = [x for x in out if (g(x, "basic_price") or 0) >= price_min]
        if price_max is not None:
            out = [x for x in out if (g(x, "basic_price") or 0) <= price_max]
        if exclude_closed:
            out = [x for x in out if (g(x, "end_date") and g(x, "end_date") > now)]
        if sort == "price":
            out = sorted(out, key=lambda x: (g(x, "basic_price") or 0), reverse=True)
        elif sort == "deadline":
            out = sorted(out, key=lambda x: (g(x, "end_date") or datetime.max))
        elif sort == "newest":
            out = sorted(out, key=lambda x: (g(x, "start_date") or datetime.min), reverse=True)
        return out

    use_api = bool(keyword or region or norm_cat or date_from or date_to)

    if use_api:
        # region 명시 없고 keyword 가 지역명이면 기관 검색으로 전환 (스마트 감지 유지)
        eff_region = region
        eff_keyword = keyword
        if not region and keyword and CrawlerService.is_region_keyword(keyword):
            eff_region, eff_keyword = keyword, None

        api_results = CrawlerService.fetch_notices(
            page=page, size=limit, keyword=eff_keyword, region=eff_region,
            category=norm_cat, date_from=date_from, date_to=date_to,
        )
        try:
            if api_results:
                CrawlerService.save_notices(db, api_results)
        except Exception as e:
            logger.warning(f"DB save error (non-fatal): {e}")

        results = _post_filter(api_results)
        # 키워드 관련성 재필터 — 조달청 OpenAPI 의 bidNtceNm/ntceInsttNm 필터가
        # 불안정해 무관한 공고가 섞이므로, 제목·기관·지역에 검색어 포함 여부로 재선별.
        term = (keyword or region or "").strip()
        if term:
            results = [
                x for x in results
                if term in ((x.get("title") or "") + (x.get("organization") or "") + (x.get("region") or ""))
            ]
        return results[:limit]

    # ── 기본 피드: DB (활성 우선) ──
    from sqlalchemy import case

    is_active = case(
        (models.Notice.end_date.is_(None), 1),
        (models.Notice.end_date > now, 0),
        else_=1,
    )
    # [Mock] 가짜 공고 제외 (개발 잔여 데이터 방어)
    query = db.query(models.Notice).filter(~models.Notice.title.like("[Mock]%"))
    if exclude_closed:
        query = query.filter(models.Notice.end_date > now).order_by(models.Notice.end_date.asc())
    else:
        query = query.order_by(is_active, models.Notice.end_date.desc())

    offset = (page - 1) * limit
    notices = query.offset(offset).limit(limit).all()

    if not notices and page == 1:
        logger.info("DB empty, fetching initial batch from API (all categories)...")
        api_data = CrawlerService.fetch_notices(page=1, size=50)
        CrawlerService.save_notices(db, api_data)
        notices = query.offset(offset).limit(limit).all()

    return notices

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
def toggle_favorite(bid_no: str, db: Session = Depends(get_db)):
    """
    Toggle Favorite status for a bid.
    """
    existing = db.query(models.Favorite).filter(models.Favorite.bid_no == bid_no).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"status": "removed", "bid_no": bid_no}
    else:
        new_fav = models.Favorite(bid_no=bid_no)
        db.add(new_fav)
        db.commit()
        return {"status": "added", "bid_no": bid_no}

@router.get("/favorites/list", response_model=List[schemas.Notice])
def get_favorites(db: Session = Depends(get_db)):
    """
    Get all favorite notices.
    """
    # Join with Notice to get full notice details
    favorites = db.query(models.Notice).join(models.Favorite).order_by(models.Favorite.created_at.desc()).all()
    return favorites


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

