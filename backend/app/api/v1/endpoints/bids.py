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
        final_price = CalculatorService.calculate_safe_bid(request.basic_price, request.rate)
        
        # Simple Safety Check (Mock logic for now - real logic depends on Lower Limit Rate)
        # Assuming standard lower limit is often around -2% to +2% range, merely checking calculation here.
        # In a real scenario, we'd compare against the 'Lower Limit Price'.
        # For this version, we mark it safe if calculation succeeds.
        
        return schemas.BidCalculationResponse(
            original_price=request.basic_price,
            rate=request.rate,
            result_price=final_price,
            is_safe=True, # Todo: Implement strict lower limit check
            warning_message=None
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/feed", response_model=List[schemas.Notice])
def get_feed(db: Session = Depends(get_db)):
    """
    Get customized notice feed.
    Currently returns all notices.
    """
    notices = db.query(models.Notice).limit(10).all()
    return notices

