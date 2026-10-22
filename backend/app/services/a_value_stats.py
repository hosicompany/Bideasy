"""금액대별 A값 실측 중앙값 — 공개 페이지(/a-value)·계산기 기본값용.

표본은 기초금액 API 구성요소 합계(tier0)로 확정된 공사 공고만 쓴다. 기초금액
(`basis_amount`)으로 밴드를 나눈다 — `basic_price` 는 추정가격이라 밴드가 밀린다.
"""
import statistics
import time

from sqlalchemy.orm import Session

from app.db import models
from app.services.lower_limits import AMOUNT_BANDS, example_basis_for_band, get_amount_band

_TTL = 3600  # 초. 수집은 하루 1회(06:40)라 1시간이면 충분하다.
_cache: dict = {"at": 0.0, "data": None}  # ponytail: 프로세스 로컬 캐시, 워커 수만큼 계산


def band_medians(db: Session) -> dict:
    if _cache["data"] is not None and time.time() - _cache["at"] < _TTL:
        return _cache["data"]
    rows = (
        db.query(models.Notice.basis_amount, models.Notice.a_value)
        .filter(models.Notice.contract_type == "CONSTRUCTION",
                models.Notice.a_value_source == "tier0",
                models.Notice.a_value > 0,
                models.Notice.basis_amount > 0)
        .all()
    )
    per: dict[str, list[tuple[float, int]]] = {}
    for basis, a in rows:
        if a >= basis:  # 구성요소 합이 기초금액 이상이면 단위 오류 — 버린다
            continue
        per.setdefault(get_amount_band(basis), []).append((basis, a))
    bands = []
    for threshold, code, label in reversed(AMOUNT_BANDS):
        xs = per.get(code, [])
        bands.append({
            "code": code,
            # 채우기 링크가 기초금액도 같은 구간으로 맞춘다 — 100억대 A값이 5억 기본값에 붙지 않게
            "example_basic": example_basis_for_band(threshold),
            "label": label,
            "n": len(xs),
            "median_a": int(statistics.median(a for _, a in xs)) if xs else None,
            "median_ratio_pct": round(statistics.median(a / b * 100 for b, a in xs), 2) if xs else None,
        })
    data = {"total": sum(b["n"] for b in bands), "bands": bands}
    _cache.update(at=time.time(), data=data)
    return data
