from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Any, Dict, Optional

from app.core.security import get_current_user_optional
from app.db.session import get_db
from app.db import models
from app.services.winning_rate import WinningRateService

router = APIRouter()

@router.get("/{bid_no}/recommend-points", response_model=Dict)
async def get_scientific_recommendation(
    bid_no: str,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
) -> Any:
    """
    기관 개찰 데이터 팩트 분석 (예측 아님).

    2026-07-17 정직성 수습: 과거 합성(Demo Mode) 데이터 생성 경로를 제거했다.
    실측 OpeningResult 가 충분하면 기술통계를, 부족하면 status=insufficient_data 를
    명시적으로 반환한다. 응답 골격(키 구성)은 기존 클라이언트와 호환 유지.
    """

    notice = db.query(models.Notice).filter(models.Notice.bid_no == bid_no).first()

    if not notice:
        return {
            "strategies": [],
            "message": "공고 정보를 찾을 수 없습니다."
        }

    agency_name = notice.organization
    basic_price = notice.basic_price

    # 1. 기관 역대 낙찰률 기술통계 (팩트 — 데이터 부족 시 insufficient_data)
    agency_stats = WinningRateService.get_agency_stats(db, agency_name)

    # 2. 낙찰률 분포 분위수 요약 (결정적 — 데이터 없으면 빈 리스트)
    mc_results = WinningRateService.run_monte_carlo_simulation(basic_price, agency_stats)

    # 3. (구) 블루오션 — 랜덤 생성이라 제거됨. 실측 분석 준비 전까지 빈 리스트.
    blue_ocean = WinningRateService.get_blue_ocean_strategy(db, bid_no)

    # 4. Phase 4: Qualification Check (로그인 사용자에 한해 본인 자격 검사)
    # 익명 호출이면 current_user 가 None → qualification 은 빈 객체로 반환.
    qualification: Dict[str, Any] = {}
    if current_user is not None:
        from app.services.qualification_checker import QualificationChecker

        notice_dict = {
            "bidNtceNm": notice.title,
            "LmtRegion": notice.region,
            # "sucsfbidMthdNm": notice.contract_method # If needed
        }
        qualification = QualificationChecker.check_qualification(notice_dict, current_user)
        
    # 5. 역대 평균 참가 수 (팩트 — 하드코딩 배수·랜덤 노이즈 제거)
    competition = WinningRateService.predict_competition_rate(db, notice)

    return {
        "agency_profile": agency_stats,
        "monte_carlo": {
            "top_rates": mc_results,
            "description": "이 기관 역대 낙찰률 분포의 분위수 요약 (p10~p90, 실측 기반)"
        },
        "blue_ocean": {
            "strategies": blue_ocean,
            "description": "실측 경쟁 밀도 분석 준비 중"
        },
        "competition": competition,
        "qualification": qualification
    }
