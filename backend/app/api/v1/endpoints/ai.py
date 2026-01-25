from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db import models
from app.services.llm_agent import llm_agent
import json
from datetime import datetime

router = APIRouter()

@router.get("/{bid_no}/analysis")
async def analyze_bid(bid_no: str, db: Session = Depends(get_db)):
    """
    Get AI Analysis for a specific bid.
    Checks DB cache first, then calls LLM if missing.
    """
    # 1. Check Cache (DB)
    cached_log = db.query(models.AIAnalysisLog).filter(models.AIAnalysisLog.bid_no == bid_no).first()
    if cached_log:
        # Return the cached JSON directly
        # Note: We assume cached_log.summary_json contains the new 'badges/check_items/tips' structure
        # If old cache exists, it might break. But for dev environment, we accept this risk or clear DB.
        return cached_log.summary_json
    
    # 2. Get Notice Content
    notice = db.query(models.Notice).filter(models.Notice.bid_no == bid_no).first()
    if not notice:
        raise HTTPException(status_code=404, detail="Notice not found")
        
    # 3. Call LLM
    analysis_result = llm_agent.analyze_notice(notice.content)
    
    # 4. Save to Cache
    new_log = models.AIAnalysisLog(
        bid_no=bid_no,
        summary_json=analysis_result, # Store the WHOLE dict here
        risk_factors=[], # Unused
        llm_model="gpt-4o-mini",
        token_usage=0, 
        created_at=datetime.utcnow()
    )
    db.add(new_log)
    db.commit()
    
    return analysis_result

