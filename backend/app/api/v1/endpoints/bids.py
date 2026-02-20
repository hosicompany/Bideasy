from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

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
    exclude_closed: bool = False, 
    page: int = 1, 
    limit: int = 20, 
    db: Session = Depends(get_db)
):
    """
    Get customized notice feed with pagination.
    - Page starts at 1
    """
    from datetime import datetime

    if keyword:
        from app.services.crawler import CrawlerService
        
        # 1. Smart Detection: Is this a region search?
        is_region = CrawlerService.is_region_keyword(keyword)
        
        # 2. Fetch from API with pagination
        # Note: API filtering is weak, so we fetch slightly more to filter client-side, 
        # but for infinite scroll with specific page, we trust API's pagination more.
        # To avoid complexity, we just pass page/size to API.
        api_results = CrawlerService.fetch_notices(page=page, size=limit, keyword=keyword if not is_region else None, region=keyword if is_region else None)
        
        # If API returns data, we process and return it.
        # Client-side filtering in this paginated context is tricky because we might filter out all 20 items.
        # For now, we trust the API or accept that some irrelevant items might appear (if API keyword search is fuzzy).
        # Actually crawler.py handles 'region' vs 'keyword' param mapping.
        
        if not api_results:
             # Try DB search if API fails or yields nothing (fallback)
             # But usually API should return data.
             pass

        # 4. Save to DB for caching (only filtered results)
        try:
             if api_results:
                CrawlerService.save_notices(db, api_results)
        except Exception as e:
            logger.warning(f"DB save error (non-fatal): {e}")
        
        return api_results
        
    else:
        # Default Feed: DB with active notices (bid still open) shown first
        from sqlalchemy import case

        now = datetime.now()

        # Use end_date (DateTime column) for reliable comparison
        # Active = bid closing date hasn't passed yet
        is_active = case(
            (models.Notice.end_date == None, 1),    # No end_date → treat as closed
            (models.Notice.end_date > now, 0),      # Still accepting bids → active
            else_=1                                  # Bid closed
        )

        query = db.query(models.Notice).order_by(
            is_active,                              # Active notices first
            models.Notice.end_date.desc()           # Then by deadline (newest first)
        )

        if exclude_closed:
            query = db.query(models.Notice).filter(
                models.Notice.end_date > now
            ).order_by(models.Notice.end_date.asc())  # Soonest deadline first

        # Pagination
        offset = (page - 1) * limit
        notices = query.offset(offset).limit(limit).all()

        if not notices and page == 1:
            # First load and no data? Fetch from API
            from app.services.crawler import CrawlerService
            logger.info("DB empty, fetching initial batch from API...")
            api_data = CrawlerService.fetch_notices(page=1, size=50)
            CrawlerService.save_notices(db, api_data)
            # Re-query
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

