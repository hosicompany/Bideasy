"""누적 개찰 통계 집계 — `opening_results` → `opening_stats`.

무엇을 만드나
------------
개찰 원장을 축(기관 · 입찰방법 · 금액대)으로 묶어 **분위수**만 남긴다.
설계 배경과 비목표는 `docs/OPENING_STATS_DESIGN.md`, 표 구조의 근거는
`models.OpeningStat` docstring 에 있다.

이 파일이 지키는 계약 넷
----------------------
1. **추정하지 않는다** — 기초금액이 없거나 기준이 어긋난 행은 표본에서 뺀다.
   `basic_price` 에 추정가격이 섞여 있던 사고(docs/PRICE_BASE_DEFECT.md) 때문에
   사정률 검사를 통과한 행만 쓴다.
2. **평균을 담지 않는다** — 사정률 평균은 실측상 전 기관이 100% 근처라 신호가
   없다. 평균을 담아 두면 언젠가 화면이 그걸 예측처럼 읽는다.
3. **표본이 모자라면 셀을 만들지 않는다** — n < `MIN_SAMPLE` 은 저장 자체를
   안 한다. 저장해 두면 결국 누군가 쓴다.
4. **버린 것을 센다** — 제외·미달 건수를 결과에 담는다. 조용한 절삭 금지.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db import models
from app.services.bid_data_quality import base_is_consistent
from app.services.lower_limits import get_amount_band

logger = get_logger(__name__)

# 표본 기간 — "지난 1년" 은 사용자에게도 자연스러운 창이고, 요율 개정(2026-01-30)
# 전후가 섞이는 것을 이 이상 넓히면 감당하기 어렵다.
DEFAULT_WINDOW_DAYS = 365

# 셀 최소 표본. arm_backtest.MIN_METHOD_N(=30)보다 낮은 이유: 저기는 arm 끼리
# **차이**를 주장하려는 것이고, 여기는 분포를 **있는 그대로** 보여주는 것뿐이다.
# 다만 10 미만은 p10/p90 이 사실상 최소·최대라 분위수라고 부르기 민망하다.
MIN_SAMPLE = 10

# 기관 무관 집계를 나타내는 값. NULL 이 아니라 빈 문자열인 이유는
# models.OpeningStat docstring 참고(Postgres UNIQUE 가 NULL 을 안 묶는다).
ALL_ORGS = ""


def _percentile(sorted_values: list[float], p: float) -> float:
    """선형보간 없는 최근접 분위수. 표본이 작아 보간의 정밀도가 무의미하다."""
    if not sorted_values:
        raise ValueError("empty sample")
    idx = int(round((len(sorted_values) - 1) * p))
    return sorted_values[max(0, min(idx, len(sorted_values) - 1))]


class _Cell:
    """한 축 조합의 표본 모음."""

    __slots__ = ("winner_rates", "reserved_ratios", "participants",
                 "first_open", "last_open")

    def __init__(self) -> None:
        self.winner_rates: list[float] = []
        self.reserved_ratios: list[float] = []
        self.participants: list[int] = []
        self.first_open: datetime | None = None
        self.last_open: datetime | None = None

    def add(self, winner_rate: float, reserved_ratio: float,
            participants: int | None, open_date: datetime | None) -> None:
        self.winner_rates.append(winner_rate)
        self.reserved_ratios.append(reserved_ratio)
        if participants and participants > 0:
            self.participants.append(participants)
        if open_date is not None:
            if self.first_open is None or open_date < self.first_open:
                self.first_open = open_date
            if self.last_open is None or open_date > self.last_open:
                self.last_open = open_date

    def to_row(self, organization: str, bid_method: str, amount_band: str,
               computed_at: datetime) -> models.OpeningStat:
        wr = sorted(self.winner_rates)
        rr = sorted(self.reserved_ratios)
        pt = sorted(self.participants)
        return models.OpeningStat(
            organization=organization,
            bid_method=bid_method,
            amount_band=amount_band,
            n=len(wr),
            period_start=self.first_open,
            period_end=self.last_open,
            winner_rate_p10=_percentile(wr, 0.10),
            winner_rate_p50=_percentile(wr, 0.50),
            winner_rate_p90=_percentile(wr, 0.90),
            reserved_ratio_p10=_percentile(rr, 0.10),
            reserved_ratio_p50=_percentile(rr, 0.50),
            reserved_ratio_p90=_percentile(rr, 0.90),
            participants_p50=int(_percentile(pt, 0.50)) if pt else None,
            participants_max=int(pt[-1]) if pt else None,
            participants_n=len(pt),
            computed_at=computed_at,
        )


def _usable(row) -> tuple[float, float] | None:
    """(낙찰 투찰률 %, 사정률 %) — 쓸 수 없는 행이면 None.

    사정률 검사를 통과 못 한 행을 빼는 건 보수적이지만 의도한 것이다.
    기준이 섞인 행 하나가 분위수를 통째로 밀어 버린다.
    """
    basic = float(row.basic_price or 0)
    reserved = float(row.reserved_price or 0)
    winner = float(row.winner_price or 0)
    if basic <= 0 or reserved <= 0 or winner <= 0:
        return None
    ratio = reserved / basic
    if not base_is_consistent(basic, reserved):
        return None
    return winner / basic * 100.0, ratio * 100.0


def rebuild(db: Session, window_days: int = DEFAULT_WINDOW_DAYS,
            now: datetime | None = None) -> dict:
    """전체 재집계. 기존 행을 지우고 새로 쓴다 — 한 트랜잭션.

    증분 갱신을 하지 않는 이유: 분위수는 부분 집계를 합칠 수 없다. 그리고
    표본이 연 2~4만 행 규모라 전량 재계산이 몇 초다. 규모가 바뀌면 그때 나눈다.
    """
    now = now or datetime.utcnow()
    since = now - timedelta(days=window_days)

    rows = (db.query(models.OpeningResult)
            .filter(models.OpeningResult.open_date >= since)
            .all())

    scanned = len(rows)
    excluded = 0
    org_cells: dict[tuple[str, str, str], _Cell] = defaultdict(_Cell)
    all_cells: dict[tuple[str, str, str], _Cell] = defaultdict(_Cell)

    for row in rows:
        vals = _usable(row)
        if vals is None:
            excluded += 1
            continue
        winner_rate, reserved_ratio = vals
        band = get_amount_band(float(row.basic_price or 0))
        method = (row.bid_method or "").strip()
        org = (row.organization or "").strip()
        pc = row.participants_count
        od = row.open_date

        # 기관 무관 셀은 항상 만든다 — 기관 표본이 모자랄 때 화면이 물러설 자리.
        all_cells[(ALL_ORGS, method, band)].add(winner_rate, reserved_ratio, pc, od)
        if org:
            org_cells[(org, method, band)].add(winner_rate, reserved_ratio, pc, od)

    computed_at = now
    keep: list[models.OpeningStat] = []
    skipped_small = 0
    for source in (all_cells, org_cells):
        for (org, method, band), cell in source.items():
            if len(cell.winner_rates) < MIN_SAMPLE:
                skipped_small += 1
                continue
            keep.append(cell.to_row(org, method, band, computed_at))

    db.query(models.OpeningStat).delete()
    db.flush()
    for stat in keep:
        db.add(stat)
    db.commit()

    summary = {
        "ok": True,
        "window_days": window_days,
        "scanned": scanned,
        "excluded_base_mismatch": excluded,
        "cells_written": len(keep),
        "cells_skipped_small": skipped_small,
        "min_sample": MIN_SAMPLE,
        "since": since.isoformat(),
    }
    logger.info(f"opening_stats.rebuild: {summary}")
    return summary


def lookup(db: Session, bid_method: str, basic_price: float | None,
           organization: str | None = None) -> models.OpeningStat | None:
    """이 공고에 맞는 통계 셀 — 기관 표본이 없으면 기관 무관 셀로 물러선다.

    **없으면 None 이다.** 근처 셀을 대신 주지 않는다 — "비슷한 금액대"로
    갈아끼우면 화면이 다른 게임의 숫자를 이 공고의 숫자처럼 보여준다.
    """
    band = get_amount_band(basic_price)
    method = (bid_method or "").strip()
    if not method or not band:
        return None

    q = db.query(models.OpeningStat).filter(
        models.OpeningStat.bid_method == method,
        models.OpeningStat.amount_band == band,
    )
    org = (organization or "").strip()
    if org:
        hit = q.filter(models.OpeningStat.organization == org).first()
        if hit is not None:
            return hit
    return q.filter(models.OpeningStat.organization == ALL_ORGS).first()
