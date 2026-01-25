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
    Get customized notice feed.
    - keyword: Filter by title (e.g. "socket", "paving")
    """
    query = db.query(models.Notice)
    if keyword:
        # Simple LIKE query
        query = query.filter(models.Notice.title.contains(keyword))
    
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

