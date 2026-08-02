"""과거 데이터 5-arm 백테스트 — 모의투찰과 같은 arm 구성으로 과거를 재평가.

왜 있나: 모의투찰(전향 실험)은 표본이 쌓이는 데 시간이 걸린다. 같은 5 arm 을
과거 개찰 데이터에 적용하면 **지금 당장** 비교표를 얻을 수 있다.

⚠️ 이건 사후 재구성(백테스트)이지 사전 등록이 아니다. 자가보정이 파라미터를
   바꾸면 과거 수치도 함께 변한다 — 방향 탐색용 참고지 증거가 아니다.
   증거로 쓸 수 있는 건 모의투찰(`mock_bidding`) 쪽이다.

⚠️ frontier_c5/c10 은 2021~2024 로 fit 해 2025 를 holdout 으로 잡은 파라미터다.
   전체 기간 수치는 **자기 학습 데이터를 포함**하므로 frontier 에 유리하게
   편향된다. 공정한 비교는 holdout 슬라이스다 — 화면에 함께 표기할 것.

판정은 `mock_bidding.judge` 를 재사용한다(§P3 판정 단일 소스). 여기서 자체
판정을 만들면 자가보정·모의투찰·백테스트가 서로 다른 말을 하게 된다.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from app.core.logging import get_logger
from app.services.autocalibrate import dataset as ds
from app.services.mock_bidding import (
    AGGRESSIVE_RATE, STANDARD_RATE, judge,
)

logger = get_logger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_BENCHMARK_RESULTS = _DATA_DIR / "benchmark_win_reach_results.json"

# 벤치마크(`BENCHMARK_WIN_REACH.md` §0.1)와 같은 holdout 연도
HOLDOUT_YEARS = (2025,)

ARM_DESC = {
    "standard": "슬라이더 기본 −2.5% — 실사용자 다수의 실제 행동",
    "active": "현 자가보정 전략 (운영 정본)",
    "frontier_c5": "무효율 캡 5% 최적 — 안전 우선",
    "frontier_c10": "무효율 캡 10% 최적 — 균형",
    "aggressive": "시장 추격 −12% — 공격 가설",
}
ARM_ORDER = ("standard", "active", "frontier_c5", "frontier_c10", "aggressive")


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """이항 비율의 Wilson 95% 신뢰구간 (%).

    표본이 작으면 넓어진다. 폭이 겹치는 두 arm 은 우열을 단정할 수 없다.
    """
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half) * 100.0, min(1.0, center + half) * 100.0)


def price_flat(r: ds.BidRecord, rate_pct: float) -> int:
    """사정률 고정 정책 — 기초금액 × (1+rate/100), 10원 절사.

    calculator.calculate_safe_bid(a_value=0) 와 같은 공식.
    """
    return math.floor(r.basic_price * (1 + rate_pct / 100.0) / 10) * 10


def price_params(r: ds.BidRecord, params: dict) -> int:
    """세그먼트 파라미터셋 가격 — optimizer.simulate_params 와 같은 공식."""
    mp = params.get(r.bid_method, params.get("DEFAULT", {}))
    p = mp.get(r.bracket) or params.get("DEFAULT", {}).get(r.bracket, [-0.3, 1.0])
    adj, margin = float(p[0]), float(p[1])
    predicted = r.basic_price * (1 + adj / 100.0)
    target_rate = r.lower_limit_rate + margin
    return math.floor(predicted * target_rate / 100.0 / 10) * 10


def tally(records: list[ds.BidRecord], price_fn) -> dict:
    """arm 하나의 무효/적중/밀림 집계 + Wilson CI."""
    win = drop = 0
    for r in records:
        lower_limit = r.reserved_price * r.lower_limit_rate / 100.0
        v = judge(price_fn(r), lower_limit, r.winner_price)
        if v == "WIN":
            win += 1
        elif v == "DROPOUT":
            drop += 1
    n = len(records)
    lo, hi = wilson_ci(win, n)
    return {
        "n": n,
        "win_rate": round(win / n * 100.0, 3) if n else 0.0,
        "dropout_rate": round(drop / n * 100.0, 3) if n else 0.0,
        "lost_rate": round((n - win - drop) / n * 100.0, 3) if n else 0.0,
        "win_ci95": [round(lo, 3), round(hi, 3)],
    }


def _frontier_params() -> dict:
    """벤치마크가 저장한 캡별 최적 파라미터셋."""
    try:
        data = json.loads(_BENCHMARK_RESULTS.read_text(encoding="utf-8"))
        return data.get("frontier", {}).get("best_params_by_cap") or {}
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"[arm_backtest] frontier 파라미터 로드 실패: {e}")
        return {}


def build_arms() -> dict:
    """5 arm 의 가격 함수. 파라미터를 못 구한 arm 은 뺀다(지어내지 않는다)."""
    arms: dict = {}
    arms["standard"] = lambda r: price_flat(r, STANDARD_RATE)

    try:
        from app.services.autocalibrate.strategy_store import get_default_store
        active = get_default_store().load_active().params
        arms["active"] = lambda r, _p=active: price_params(r, _p)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[arm_backtest] active 전략 로드 실패 — arm 제외: {e}")

    frontier = _frontier_params()
    for name, cap in (("frontier_c5", "5"), ("frontier_c10", "10")):
        p = frontier.get(cap)
        if p is not None:
            arms[name] = lambda r, _p=p: price_params(r, _p)

    arms["aggressive"] = lambda r: price_flat(r, AGGRESSIVE_RATE)
    return {k: arms[k] for k in ARM_ORDER if k in arms}


def run(db=None, bid_method: str | None = None) -> dict:
    """5 arm 을 과거 데이터에 적용해 슬라이스별 지표를 낸다.

    db 를 주면 누적 개찰결과(opening_results)도 병합한다.
    """
    records = ds.load_records(db=db)
    if not records:
        return {"available": False, "reason": "과거 개찰 데이터가 없습니다.", "arms": {}}

    if bid_method:
        records = [r for r in records if r.bid_method == bid_method]
        if not records:
            return {"available": False, "reason": "조건에 맞는 데이터가 없습니다.", "arms": {}}

    _, holdout = ds.split_by_year(records, HOLDOUT_YEARS)
    qual = [r for r in records if r.bid_method == "적격심사제"]
    qual_hold = [r for r in qual if r.year in HOLDOUT_YEARS]

    slices = {
        "overall": records,
        "holdout": holdout,
        "qualification": qual,
        "qualification_holdout": qual_hold,
    }

    arms_fn = build_arms()
    out: dict = {
        "available": True,
        "n_records": len(records),
        "holdout_years": list(HOLDOUT_YEARS),
        "slice_sizes": {k: len(v) for k, v in slices.items()},
        "arms": {},
        # 화면이 이 경고를 반드시 함께 보여줘야 오해가 없다
        "caveats": [
            "백테스트는 사후 재구성이라 자가보정이 파라미터를 바꾸면 과거 수치도 함께 변한다 — 참고용이지 증거가 아니다.",
            "frontier_c5/c10 은 2021~2024 로 학습해 2025 를 holdout 으로 잡은 파라미터라, 전체 기간 열에서는 자기 학습 데이터가 섞여 유리하게 편향된다. 공정한 비교는 holdout 열이다.",
            "적중률은 내부 참고용이며 대외 표기는 금지(전역 규칙 §4-2).",
        ],
    }

    for name, fn in arms_fn.items():
        entry = {"desc": ARM_DESC.get(name, "")}
        for slice_name, recs in slices.items():
            if recs:
                entry[slice_name] = tally(recs, fn)
        by_year: dict[int, list] = {}
        for r in records:
            by_year.setdefault(r.year, []).append(r)
        entry["by_year"] = {str(y): tally(rs, fn) for y, rs in sorted(by_year.items())}
        out["arms"][name] = entry

    return out
