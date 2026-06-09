"""
데이터 적재·정제 모듈
======================
과거 개찰 결과(opening_results_*.json)를 로드·정제해서
백테스트 / 최적화 / 가드가 공유하는 단일 데이터 소스를 제공한다.

기존에 optimize_weighted.py:load_all(), mock_bidding_test.py:load_exam_data()
등 3곳에 중복되어 있던 로딩 로직을 통합.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

# backend/app/services/autocalibrate/dataset.py → backend/data
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
_DATA_DIR = _BACKEND_DIR / "data"

# 금액대 5단계 (calculator._get_price_bracket 과 동일 경계)
BRACKETS = ["small", "medium", "large", "xlarge", "xxlarge"]
# 전략이 정의된 입찰방법 (DEFAULT 는 폴백)
KNOWN_METHODS = ["적격심사제", "소액수의견적"]


def get_bracket(basic_price: float) -> str:
    """기초금액 → 금액대 (calculator._get_price_bracket 과 동일)."""
    if basic_price < 1e8:
        return "small"
    elif basic_price < 5e8:
        return "medium"
    elif basic_price < 1e9:
        return "large"
    elif basic_price < 5e9:
        return "xlarge"
    else:
        return "xxlarge"


@dataclass
class BidRecord:
    """개찰 결과 한 건 (정제·검증 완료). 원본 + 파생 필드."""

    bid_no: str
    title: str
    org: str
    bid_method: str
    basic_price: float
    estimated_price: float
    reserved_price: float       # 실제 예정가격 (정답)
    winner_price: float          # 실제 낙찰가 (정답)
    winner_rate: float           # 실제 낙찰률 (정답)
    lower_limit_rate: float
    year: int
    bracket: str = ""

    def __post_init__(self):
        if not self.bracket:
            self.bracket = get_bracket(self.basic_price)

    @property
    def reserved_ratio(self) -> float:
        """사정비율 r = 예정가격 / 기초금액 — 위험 모델의 핵심 변수."""
        return self.reserved_price / self.basic_price if self.basic_price > 0 else 0.0

    @property
    def segment(self) -> tuple[str, str]:
        return (self.bid_method, self.bracket)


def _load_db_records(db, existing_bid_nos: set) -> list[BidRecord]:
    """누적 opening_results 테이블(매일 크롤 적재)에서 BidRecord 생성.

    정적 파일과 중복(bid_no)은 제외. OpeningResult 는 공사 개찰결과라
    lower_limit_rate=87.745(공사) 기본. estimated_price 는 reserved_price 로 대체.
    """
    out: list[BidRecord] = []
    try:
        from app.db import models
        rows = (
            db.query(models.OpeningResult)
            .filter(
                models.OpeningResult.basic_price > 0,
                models.OpeningResult.winner_price > 0,
                models.OpeningResult.reserved_price > 0,
            )
            .all()
        )
    except Exception:
        return out
    for r in rows:
        if not r.bid_no or r.bid_no in existing_bid_nos:
            continue
        existing_bid_nos.add(r.bid_no)
        year = r.open_date.year if getattr(r, "open_date", None) else 0
        out.append(BidRecord(
            bid_no=r.bid_no,
            title="",
            org=r.organization or "",
            bid_method=r.bid_method or "",
            basic_price=float(r.basic_price),
            estimated_price=float(r.reserved_price or 0),
            reserved_price=float(r.reserved_price),
            winner_price=float(r.winner_price),
            winner_rate=float(r.winner_rate or 0),
            lower_limit_rate=87.745,
            year=year,
        ))
    return out


def load_records(
    year_range: tuple[int, int] = (2021, 2027),
    data_dir: Path = _DATA_DIR,
    db=None,
) -> list[BidRecord]:
    """opening_results_{year}.json 들을 로드·정제 (+ db 제공 시 누적 DB 병합).

    유효 조건: basic_price > 0 AND winner_price > 0 AND reserved_price > 0.
    db 전달 시 매일 쌓이는 opening_results 테이블도 합쳐 최신 시장 반영.
    """
    records: list[BidRecord] = []
    for year in range(year_range[0], year_range[1]):
        f = data_dir / f"opening_results_{year}.json"
        if not f.exists():
            continue
        with open(f, encoding="utf-8") as fh:
            items = json.load(fh)
        for item in items:
            bp = item.get("basic_price", 0) or 0
            wp = item.get("winner_price", 0) or 0
            rp = item.get("reserved_price", 0) or 0
            if bp <= 0 or wp <= 0 or rp <= 0:
                continue
            od = item.get("open_date", "")
            y = (
                int(od[:4])
                if od and len(od) >= 4 and od[:4].isdigit()
                else year
            )
            records.append(
                BidRecord(
                    bid_no=item.get("bid_no", ""),
                    title=item.get("title", ""),
                    org=item.get("org", ""),
                    bid_method=item.get("bid_method", ""),
                    basic_price=float(bp),
                    estimated_price=float(item.get("estimated_price", 0) or 0),
                    reserved_price=float(rp),
                    winner_price=float(wp),
                    winner_rate=float(item.get("winner_rate", 0) or 0),
                    lower_limit_rate=float(
                        item.get("lower_limit_rate", 87.745) or 87.745
                    ),
                    year=y,
                )
            )
    # 누적 DB 병합 (db 제공 시) — 매일 크롤된 최신 개찰결과 포함
    if db is not None:
        records.extend(_load_db_records(db, {r.bid_no for r in records}))
    return records


def data_fingerprint(records: list[BidRecord]) -> str:
    """건수 + 정렬된 bid_no 해시. 같은 데이터로 재최적화 시 스킵 판단용."""
    ids = sorted(r.bid_no for r in records)
    h = hashlib.sha256("|".join(ids).encode("utf-8")).hexdigest()[:16]
    return f"n{len(records)}_{h}"


def filter_segment(
    records: list[BidRecord], method: str, bracket: str
) -> list[BidRecord]:
    """특정 (입찰방법, 금액대) 세그먼트만 추출."""
    return [r for r in records if r.bid_method == method and r.bracket == bracket]


def iter_segments(records: list[BidRecord]) -> list[tuple[str, str]]:
    """데이터에 실제로 존재하는 (method, bracket) 세그먼트 목록."""
    seen = {(r.bid_method, r.bracket) for r in records}
    return sorted(seen)


def split_by_year(
    records: list[BidRecord], holdout_years: tuple[int, ...]
) -> tuple[list[BidRecord], list[BidRecord]]:
    """walk-forward 검증용: (학습셋, hold-out셋) 분리."""
    train = [r for r in records if r.year not in holdout_years]
    holdout = [r for r in records if r.year in holdout_years]
    return train, holdout
