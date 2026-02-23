"""기관 프로파일링 API — 낙찰 패턴 분석"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import require_tier
from app.db.models import User
from app.schemas.agency import AgencyProfileRequest, AgencyProfile
from app.services.agency_profiler import AgencyProfiler

router = APIRouter()


@router.post("/profile", response_model=AgencyProfile)
def get_agency_profile(
    req: AgencyProfileRequest,
    current_user: User = Depends(require_tier("pro_plus")),
    db: Session = Depends(get_db),
):
    """
    기관명을 입력하면 과거 낙찰 데이터를 분석하여
    평균 낙찰률, 분포, 투찰 전략 추천을 반환합니다.
    """
    try:
        result = AgencyProfiler.analyze(req.organization, req.months)
        return AgencyProfile(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"기관 프로파일링 실패: {e}")
