from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.schemas import bid as schemas
from app.services.calculator import CalculatorService
from app.db import models

router = APIRouter()

@router.post("/calculate", response_model=schemas.BidCalculationResponse)
def calculate_bid(request: schemas.BidCalculationRequest):
    """
    Calculate safe bid price based on basic price and rate.
    Applies strict 1-won truncation.
    """
    try:
        # Get Contract Type or Default
        contract_type = "CONSTRUCTION" # Default if not provided
        
        final_price = CalculatorService.calculate_safe_bid(request.basic_price, request.rate)
        
        # Real Logic: Lower Limit Check
        # Calc expected price: Basic Price * Lower Limit Rate
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

@router.get("/feed", response_model=List[schemas.Notice])
def get_feed(keyword: str = None, db: Session = Depends(get_db)):
    """
    Get customized notice feed with client-side filtering.
    - Fetches bulk results from API
    - Applies strict client-side filtering based on keyword
    - Region keywords filter by organization name
    - General keywords filter by title
    """
    if keyword:
        from app.services.crawler import CrawlerService
        import sys
        
        # 1. Smart Detection: Is this a region search?
        is_region = CrawlerService.is_region_keyword(keyword)
        print(f"Smart Search: '{keyword}' (Region: {is_region})", flush=True)
        sys.stdout.flush()
        
        # 2. Fetch MORE results from API (API filtering is unreliable)
        # We fetch 500 and filter client-side for accuracy
        api_results = CrawlerService.fetch_notices(size=500)
        
        if not api_results:
            print("No API results, falling back to DB search", flush=True)
            query = db.query(models.Notice).filter(models.Notice.title.contains(keyword))
            return query.limit(30).all()
        
        # 3. CLIENT-SIDE FILTERING (the key fix!)
        filtered_results = []
        keyword_lower = keyword.lower()
        
        for item in api_results:
            title = item.get("title", "").lower()
            organization = item.get("organization", "").lower()
            
            if is_region:
                # For region search: match organization name
                if keyword_lower in organization or keyword_lower in title:
                    filtered_results.append(item)
            else:
                # For keyword search: match title only
                if keyword_lower in title:
                    filtered_results.append(item)
        
        print(f"Filtered: {len(filtered_results)}/{len(api_results)} match '{keyword}'", flush=True)
        
        # Limit to 30 results
        filtered_results = filtered_results[:30]
        
        if not filtered_results:
            print(f"No matches for '{keyword}', returning empty", flush=True)
            return []
        
        # 4. Save to DB for caching (only filtered results)
        try:
            CrawlerService.save_notices(db, filtered_results)
        except Exception as e:
            print(f"DB save error (non-fatal): {e}", flush=True)
        
        # 5. Return filtered results directly (includes all extended fields)
        print(f"Returning {len(filtered_results)} notices with extended data", flush=True)
        return filtered_results
        
    else:
        # Default Feed (Local DB)
        query = db.query(models.Notice).order_by(models.Notice.start_date.desc())
        notices = query.limit(50).all()
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
            print("Auto-migration: Adding contract_type column...")
            db.rollback() # Reset transaction
            db.execute(text("ALTER TABLE notices ADD COLUMN contract_type VARCHAR DEFAULT 'CONSTRUCTION'"))
            db.commit()

        print("Triggering Crawl...")
        notices = CrawlerService.fetch_notices(size=50)
        saved_count = CrawlerService.save_notices(db, notices)
        return {"message": "Crawl Success", "fetched": len(notices), "saved": saved_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{bid_no}/analysis", response_model=schemas.BidAnalysisResponse)
def get_bid_analysis(bid_no: str, db: Session = Depends(get_db)):
    """
    Get AI Analysis for a specific bid.
    Checks cache first, then calls LLM if needed.
    """
    # 1. Check Cache
    cached = db.query(models.AIAnalysisLog).filter(models.AIAnalysisLog.bid_no == bid_no).first()
    if cached:
        # Convert JSON back to objects
        risks = [schemas.RiskFactor(**r) for r in cached.risk_factors]
        return schemas.BidAnalysisResponse(summary=cached.summary_json, risks=risks)

    # 2. Get Notice info for Context
    notice = db.query(models.Notice).filter(models.Notice.bid_no == bid_no).first()
    if not notice:
        raise HTTPException(status_code=404, detail="Notice not found")

    # 3. Call LLM Agent
    from app.services.llm_agent import llm_agent
    from app.services.scraper import ScraperService
    
    # RAG: Fetch Real Content
    print(f"Scraping URL: {notice.content}")
    real_content = ScraperService.fetch_page_content(notice.content)
    
    if not real_content:
        # Fallback to basic context if scraping fails
        context_text = f"""
        공고명: {notice.title}
        공고번호: {notice.bid_no}
        기초금액: {notice.basic_price}
        상세링크: {notice.content}
        """
    else:
        # Use Real Content (Truncated handled in scraper)
        context_text = f"""
        [공고 요약 정보]
        공고명: {notice.title}
        기초금액: {notice.basic_price}

        [실제 공고 본문 (Scraped)]
        {real_content}
        """
    
    result = llm_agent.analyze_notice(context_text)
    
    # 4. Save to Cache
    new_log = models.AIAnalysisLog(
        bid_no=bid_no,
        summary_json=result.get("summary", []),
        risk_factors=result.get("risks", []),
        token_usage=0 
    )
    db.add(new_log)
    db.commit()

    risks = [schemas.RiskFactor(**r) for r in result.get("risks", [])]
    return schemas.BidAnalysisResponse(summary=result.get("summary", []), risks=risks)

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

