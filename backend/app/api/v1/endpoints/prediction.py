from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any, Dict

from app.db.session import get_db
from app.db import models
from app.services.winning_rate import WinningRateService

router = APIRouter()

@router.get("/{bid_no}/recommend points", response_model=Dict)
async def get_scientific_recommendation(
    bid_no: str,
    db: Session = Depends(get_db)
) -> Any:
    """
    Get Scientific Bidding Recommendations (Phase 3).
    Returns 3 strategies:
    1. Agency Stats (Safe)
    2. Monte Carlo (Probabilistic)
    3. Blue Ocean (Strategy)
    """
    
    # 1. Get Bid Info to find Agency
    # Note: frontend might pass agency_name directly if bid_no is temporary?
    # For now, look up by bid_no.
    notice = db.query(models.Notice).filter(models.Notice.bid_no == bid_no).first()
    
    if not notice:
        # Fallback or Error
        # If user is in Calculator for a bid not in DB yet (e.g. just viewed), it should be in DB due to crawler.
        # But for robustness, we can accept query params or return default.
        return {
            "strategies": [],
            "message": "공고 정보를 찾을 수 없습니다."
        }
        
    agency_name = notice.organization
    basic_price = notice.basic_price
    
    # 2. Run Algo 1, 2, 3 (Existing)
    # Algo 1: Agency Stats
    agency_stats = WinningRateService.get_agency_stats(db, agency_name)
    
    # Algo 2: Monte Carlo
    mc_results = WinningRateService.run_monte_carlo_simulation(basic_price, agency_stats)
    
    # Algo 3: Blue Ocean
    blue_ocean = WinningRateService.get_blue_ocean_strategy(db, bid_no)

    # 4. Phase 4: Qualification Check
    # Get User (Mock ID 1)
    user = db.query(models.User).filter(models.User.id == 1).first()
    qualification = {}
    
    if user:
        from app.services.qualification_checker import QualificationChecker
        # Convert SQLAlchemy model to Dict-like for Checker if needed, but Checker expects model for User and Dict for Notice
        # Notice is model, convert to dict for checker compatibility or update checker
        # Let's adjust checker call to pass model.Notice as dict
        notice_dict = {
            "bidNtceNm": notice.title,
            "LmtRegion": notice.region,
            # "sucsfbidMthdNm": notice.contract_method # If needed
        }
        
        qualification = QualificationChecker.check_qualification(notice_dict, user)
        
    # 5. Algo 4: Competition Prediction
    competition = WinningRateService.predict_competition_rate(notice)
    
    # 3. Format Response
    return {
        "agency_profile": agency_stats,
        "monte_carlo": {
            "top_rates": mc_results,
            "description": "가상 투찰 1,000회 시뮬레이션 중 가장 많이 당첨된 구간"
        },
        "blue_ocean": {
            "strategies": blue_ocean,
            "description": "경쟁사 분포 분석 기반 틈새 시장"
        },
        "competition": competition,
        "qualification": qualification
    }
