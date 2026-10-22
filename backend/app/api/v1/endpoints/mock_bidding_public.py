"""모의투찰 공개 요약 — 랜딩·성적표 페이지용. 인증 불필요.

보여주는 것은 유효율(무효)·오차·표본 진행률뿐이다. 낙찰률·등수는
`services.mock_bidding.public_summary` 가 애초에 만들지 않는다(설계 §0.6).
"""
import time

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services import mock_bidding as mb

router = APIRouter()

_CACHE_TTL = 600  # 초. 주 1회 갱신 지표라 10분이면 충분하다.
_cache: dict = {"at": 0.0, "data": None}  # ponytail: 프로세스 로컬 캐시, 워커 수만큼 중복 계산


@router.get("/public-summary")
def public_summary(response: Response, db: Session = Depends(get_db)):
    if _cache["data"] is None or time.time() - _cache["at"] > _CACHE_TTL:
        _cache["data"] = mb.public_summary(db)
        _cache["at"] = time.time()
    response.headers["Cache-Control"] = "public, max-age=600"
    return _cache["data"]
