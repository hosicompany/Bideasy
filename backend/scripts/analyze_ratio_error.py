"""사정률 예측 오차(§0.2 4차 지표) 분해·진단·개선안 검증.

    cd backend
    python scripts/analyze_ratio_error.py --exp all

관련 정본: `docs/MOCK_BIDDING_DESIGN.md` §0.2(지표)·§6(오답노트)·§7(함정)
          `docs/BENCHMARK_WIN_REACH.md` §0(사전등록)·§3(walk-forward 과적합)

이 스크립트가 답하는 질문 셋:

1. **identifiability** — `adjustment` 는 사정률 예측인가?
   목적함수 J 는 `(adj, margin)` 을 오직 곱 `(1+adj/100)×(하한율+margin)` 으로만
   본다(simulate_params 의 가격도, risk_model 의 임계비율 r* 도). 즉 같은 곱을
   주는 (adj, margin) 조합은 J 가 **완전히 같다** — 최적화가 adj 를 사정률로
   식별할 근거가 없다. 그런데 채점은 `reserved_ratio_predicted = 1+adj/100` 을
   사정률 예측으로 읽는다. 이 실험이 그 괴리를 수치로 보인다.

2. **segments** — 운영 모의투찰 표본에서 오차를 세그먼트별로 분해한다
   (금액대 × 입찰방법 × 기관 × A값 유무). MAE 를 **편향**과 **산포**로 가른다:
   adjustment 는 중심만 옮길 수 있으므로, 그 세그먼트에서 가능한 최선의 상수
   (실제 사정률의 중앙값)를 썼을 때의 MAE 가 개선 여지의 바닥(oracle)이다.
   기초금액 일관성(0.94~1.06) 통과분만 쓰고 제외 수를 함께 보고한다.

3. **walkforward** — 개선안(사정률 고정)을 기존 백테스트 경로로 검증한다.
   연도를 하나씩 holdout 으로 빼고 학습→평가를 반복해 과적합을 확인한다
   (BENCHMARK_WIN_REACH.md §3 과 같은 방식).

⛔ 이 스크립트는 전략을 승격하지 않는다(§P5). 파라미터 저장소에 쓰지 않고
   운영 DB 도 SELECT 만 한다. 산출물은 제안과 검증 수치까지다.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics as st
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.autocalibrate import dataset as ds                      # noqa: E402
from app.services.autocalibrate.optimizer import (                        # noqa: E402
    DEFAULT_ETA,
    DEFAULT_GAMMA,
    DEFAULT_LAMBDA,
    DEFAULT_TAU,
    SEGMENT_DROPOUT_HARD_LIMIT,
    objective_value,
    optimize_all,
    simulate_params,
)
from app.services.autocalibrate.risk_model import ReservedRatioModel      # noqa: E402
from app.services.autocalibrate.strategy_store import get_default_store   # noqa: E402
from app.services.bid_data_quality import (                               # noqa: E402
    BASE_RATIO_MAX,
    BASE_RATIO_MIN,
    base_is_consistent,
)
from app.services.bid_metrics import wilson_ci                            # noqa: E402

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTS_PATH = DATA_DIR / "ratio_error_analysis.json"

# optimizer._ADJ_RANGE/_MARGIN_RANGE 와 같은 값 (private 이라 출처 명시 후 복제)
GRID_ADJ = [x / 10 for x in range(-10, 16)]        # -1.0 ~ 1.5
GRID_MARGIN = [x / 10 for x in range(0, 16)]       # 0.0 ~ 1.5

# 개선안의 margin 격자 — adj 를 고정하면 곱의 도달 범위가 좁아지므로,
# **현행 격자가 만들 수 있는 곱 전체를 덮도록** 넓힌다. 안 넓히면 개선안이
# 진 것이 아니라 갈 수 있는 가격이 줄어서 진 것이 된다(비교가 성립 안 함).
#
# 폭뿐 아니라 **해상도**도 맞춰야 한다. 현행은 두 축이라 곱의 격자가 훨씬
# 촘촘하다 — adj 0.1%p 는 곱으로 약 0.09(=0.001×89.745), margin 0.1 은 0.1 이라
# 둘이 엇갈리며 0.01 수준의 격자를 만든다. 한 축만 0.1 로 두면 개선안은 늘
# 0.1 단위에서만 멈추므로, 그 차이가 성능차로 오독된다.


def pinned_margin_grid(step: float, pinned_adj: float,
                       lower_rate: float) -> list[float]:
    """adj 를 고정한 채 현행 2축 격자의 곱 전체를 재현하는 margin 격자.

    경계를 상수로 박지 않고 **커버리지 조건에서 유도한다.** 상수로 두면 고정값이
    커질수록 아래쪽이, 작아질수록 위쪽이 조용히 잘려 나가는데, 그러면 개선안이
    진 것이 아니라 갈 수 있는 가격이 줄어서 진 것이 된다 — 그리고 그 사실은
    수치만 봐서는 구분되지 않는다.
    """
    scale = 1.0 + pinned_adj / 100.0
    lo_mult = (1.0 + GRID_ADJ[0] / 100.0) * (lower_rate + GRID_MARGIN[0])
    hi_mult = (1.0 + GRID_ADJ[-1] / 100.0) * (lower_rate + GRID_MARGIN[-1])
    lo = math.floor((lo_mult / scale - lower_rate) / step) * step
    hi = math.ceil((hi_mult / scale - lower_rate) / step) * step
    n = int(round((hi - lo) / step))
    return [round(lo + i * step, 6) for i in range(n + 1)]


MIN_SAMPLE = 10          # optimizer.optimize_all 과 동일한 희소 세그먼트 기준
MIN_CENTER_SAMPLE = 30   # risk_model.MIN_SEGMENT_SAMPLE 과 같은 규율
CENTER_SHRINKAGE_K = 25.0  # risk_model.SHRINKAGE_K 와 같은 값


# ──────────────────────────────────────────────────────────────
# §A 공통 — 가격·판정·지표
# ──────────────────────────────────────────────────────────────

def params_of(params: dict, r: ds.BidRecord) -> tuple[float, float]:
    """레코드에 적용될 (adjustment, margin) — evaluate_params 와 같은 조회 순서."""
    mp = params.get(r.bid_method, params.get("DEFAULT", {}))
    p = mp.get(r.bracket) or params.get("DEFAULT", {}).get(r.bracket, [-0.3, 1.0])
    return float(p[0]), float(p[1])


def price_of(r: ds.BidRecord, adj: float, margin: float) -> float:
    """투찰가 — evaluate_params(optimizer.py:282-284) 공식 그대로."""
    predicted = r.basic_price * (1 + adj / 100.0)
    return math.floor(predicted * (r.lower_limit_rate + margin) / 100.0 / 10) * 10


def tally(records: list[ds.BidRecord], params: dict) -> dict:
    """win/dropout + 사정률 예측 오차. 균등 가중(holdout 평가용).

    ratio_error 정의는 채점(`score_mock_bid`)과 동일하다 —
    |예정가격/기초금액 − (1+adj/100)|.
    """
    win = drop = 0
    errs: list[float] = []
    signed: list[float] = []
    for r in records:
        adj, margin = params_of(params, r)
        price = price_of(r, adj, margin)
        limit = r.reserved_price * r.lower_limit_rate / 100.0
        if price < limit:
            drop += 1
        elif price <= r.winner_price:
            win += 1
        pred = 1.0 + adj / 100.0
        errs.append(abs(r.reserved_ratio - pred))
        signed.append(pred - r.reserved_ratio)
    n = len(records)
    lo, hi = wilson_ci(win, n) if n else (0.0, 0.0)
    return {
        "n": n,
        "win_rate": round(win / n * 100.0, 3) if n else 0.0,
        "win_ci95": [round(lo, 3), round(hi, 3)],
        "dropout_rate": round(drop / n * 100.0, 3) if n else 0.0,
        "ratio_mae": round(sum(errs) / len(errs), 6) if errs else None,
        "ratio_bias": round(sum(signed) / len(signed), 6) if signed else None,
        "ratio_p90": round(sorted(errs)[int(0.9 * (len(errs) - 1))], 6) if errs else None,
    }


def oracle_ratio_mae(records: list[ds.BidRecord], by_segment: bool = True) -> float:
    """사정률 예측의 이론 바닥 — 세그먼트별 중앙값을 사후에 알았을 때의 MAE.

    MAE 를 최소화하는 상수는 중앙값이다. 이보다 낮출 수는 없다(상수 예측 한).
    """
    groups: dict = {}
    for r in records:
        key = r.segment if by_segment else "ALL"
        groups.setdefault(key, []).append(r.reserved_ratio)
    total = err = 0.0
    for vals in groups.values():
        med = st.median(vals)
        err += sum(abs(v - med) for v in vals)
        total += len(vals)
    return round(err / total, 6) if total else 0.0


# ──────────────────────────────────────────────────────────────
# §B 실험 1 — adjustment 는 식별되는가
# ──────────────────────────────────────────────────────────────

def _modal_lower_rates(records: list[ds.BidRecord]) -> dict:
    """세그먼트별 최빈 낙찰하한율 — 곱 환산의 기준."""
    counts: dict = {}
    for r in records:
        counts.setdefault(r.segment, {}).setdefault(r.lower_limit_rate, 0)
        counts[r.segment][r.lower_limit_rate] += 1
    return {seg: max(c.items(), key=lambda kv: kv[1])[0] for seg, c in counts.items()}


def _best_on_grid(seg: list[ds.BidRecord], risk_model: ReservedRatioModel,
                  method: str, bracket: str, lower_rate: float,
                  adj_grid, margin_grid) -> tuple[float, tuple[float, float]]:
    """격자에서 목적함수 J 를 최대화하는 (adj, margin) 과 그 J."""
    best_j, best_p = -float("inf"), None
    for a in adj_grid:
        for m in margin_grid:
            sim = simulate_params(seg, a, m, None)
            e = risk_model.dropout_probability(a, m, method, bracket, lower_rate)
            j = objective_value(sim, e, a, m, None, DEFAULT_LAMBDA,
                                DEFAULT_GAMMA, DEFAULT_TAU, DEFAULT_ETA)
            if j > best_j:
                best_j, best_p = j, (a, m)
    return best_j, best_p


def run_identifiability(records: list[ds.BidRecord], active_params: dict) -> dict:
    """J 가 (adj, margin) 을 곱으로만 본다는 것을 수치로 확인한다.

    ① 운영 active 파라미터의 세그먼트별 adj 와 **유효 여유분** m_eff 를 나란히
       본다. m_eff = (1+adj/100)(L+margin) − L = 하한율 위 실제 쿠션(%p).
    ② 같은 곱을 주는 다른 (adj, margin) 로 바꿔치기해 win/dropout 이 그대로인지,
       ratio_error 만 움직이는지 본다.
    """
    L_REF = 89.745  # 2026 시행 10억 미만 공사 하한율 — 표기용 기준

    rows = []
    for method in ("적격심사제", "소액수의견적"):
        for bracket in ds.BRACKETS:
            p = (active_params.get(method) or {}).get(bracket)
            if not p:
                continue
            adj, margin = float(p[0]), float(p[1])
            mult = (1 + adj / 100.0) * (L_REF + margin)
            rows.append({
                "segment": f"{method}/{bracket}",
                "adjustment": adj,
                "margin": margin,
                "implied_ratio_pred": round(1 + adj / 100.0, 5),
                "multiplier": round(mult, 4),
                "effective_margin_pp": round(mult - L_REF, 4),
            })
    adjs = [r["adjustment"] for r in rows]
    effs = [r["effective_margin_pp"] for r in rows]

    # ② 곱을 보존한 재배분 — adj 를 전 세그먼트 공통 −0.1 로 밀고 margin 으로 흡수.
    # 곱은 하한율에 의존하므로 표기용 L_REF 가 아니라 **그 세그먼트 레코드의
    # 최빈 하한율**로 환산한다. 안 그러면 하한율이 다른 세그먼트에서 곱이 어긋나고,
    # 그 어긋남이 "재배분의 효과"로 잘못 읽힌다.
    PIN = -0.1
    modal_lower = _modal_lower_rates(records)
    swapped: dict = {}
    for method, brackets in active_params.items():
        swapped[method] = {}
        for bracket, p in brackets.items():
            adj, margin = float(p[0]), float(p[1])
            L = modal_lower.get((method, bracket), L_REF)
            mult = (1 + adj / 100.0) * (L + margin)
            swapped[method][bracket] = [PIN, round(mult / (1 + PIN / 100.0) - L, 4)]

    base = tally(records, active_params)
    swap = tally(records, swapped)

    # ③ 목적함수 동등성 — 축을 하나 줄여도 도달 가능한 최선의 J 가 같은가.
    # win/dropout 의 소수점 출렁임은 격자·10원 절사의 부산물이라, "성능을 팔아
    # 지표를 샀다"는 반론은 이 표로만 정확히 반박된다.
    rm = ReservedRatioModel.fit(records, None)
    parity = []
    for method, bracket in ds.iter_segments(records):
        seg = ds.filter_segment(records, method, bracket)
        if len(seg) < 100:
            continue
        lower = seg[0].lower_limit_rate
        j2, p2 = _best_on_grid(seg, rm, method, bracket, lower,
                               GRID_ADJ, GRID_MARGIN)
        j1, p1 = _best_on_grid(seg, rm, method, bracket, lower,
                               [PIN], pinned_margin_grid(0.02, PIN, lower))
        parity.append({
            "segment": f"{method}/{bracket}",
            "n": len(seg),
            "free_2axis": {"adj": p2[0], "margin": p2[1], "objective": round(j2, 6),
                           "multiplier": round((1 + p2[0] / 100) * (lower + p2[1]), 4)},
            "pinned_1axis": {"adj": p1[0], "margin": p1[1], "objective": round(j1, 6),
                             "multiplier": round((1 + p1[0] / 100) * (lower + p1[1]), 4)},
            "objective_delta": round(j1 - j2, 6),
        })

    return {
        "objective_parity": sorted(parity, key=lambda d: -d["n"]),
        "note": (
            "J 는 (adj, margin) 을 곱 (1+adj/100)×(하한율+margin) 으로만 본다 — "
            "가격(simulate_params)도 임계비율(risk_model.critical_ratio)도 그렇다. "
            "따라서 곱이 같은 조합은 목적함수가 동일하고, adj 를 사정률로 "
            "식별할 근거가 최적화 안에 없다."
        ),
        "active_segments": sorted(rows, key=lambda d: d["segment"]),
        "adjustment_spread_pp": round(max(adjs) - min(adjs), 3) if adjs else None,
        "effective_margin_spread_pp": round(max(effs) - min(effs), 3) if effs else None,
        "iso_product_swap": {
            "pinned_adjustment": PIN,
            "before": base,
            "after": swap,
            "win_delta_pp": round(swap["win_rate"] - base["win_rate"], 3),
            "dropout_delta_pp": round(swap["dropout_rate"] - base["dropout_rate"], 3),
            "ratio_mae_delta": round(swap["ratio_mae"] - base["ratio_mae"], 6),
        },
    }


# ──────────────────────────────────────────────────────────────
# §C 개선안 — 사정률 중심을 데이터에서 고정하고 margin 만 최적화
# ──────────────────────────────────────────────────────────────

def fit_ratio_centers(
    records: list[ds.BidRecord],
    min_n: int = MIN_CENTER_SAMPLE,
    k: float = CENTER_SHRINKAGE_K,
) -> dict:
    """세그먼트별 사정률 중심 r̂ — 계층 폴백 + shrinkage.

    risk_model 이 분포(μ, σ)에 쓰는 것과 같은 규율을 중심 추정에도 쓴다.
    MAE 를 최소화하는 상수는 평균이 아니라 **중앙값**이므로 중앙값을 쓴다.
    표본이 얕은 세그먼트는 부모(입찰방법 → 전역) 쪽으로 당긴다 — 얕은 표본의
    중앙값을 그대로 믿으면 그게 곧 과적합이다.
    """
    by_seg: dict = {}
    by_method: dict = {}
    all_vals: list[float] = []
    for r in records:
        if r.reserved_ratio <= 0:
            continue
        by_seg.setdefault(r.segment, []).append(r.reserved_ratio)
        by_method.setdefault(r.bid_method, []).append(r.reserved_ratio)
        all_vals.append(r.reserved_ratio)
    if not all_vals:
        return {"global": 1.0, "by_method": {}, "by_segment": {}}

    g = st.median(all_vals)
    m_centers = {}
    for method, vals in by_method.items():
        if len(vals) >= min_n:
            w = len(vals) / (len(vals) + k)
            m_centers[method] = w * st.median(vals) + (1 - w) * g
        else:
            m_centers[method] = g
    s_centers = {}
    for seg, vals in by_seg.items():
        parent = m_centers.get(seg[0], g)
        w = len(vals) / (len(vals) + k)
        s_centers[seg] = w * st.median(vals) + (1 - w) * parent
    return {
        "global": g,
        "by_method": m_centers,
        "by_segment": s_centers,
        "n_by_segment": {f"{m}/{b}": len(v) for (m, b), v in by_seg.items()},
    }


def pinned_adjustment(centers: dict, method: str, bracket: str) -> float:
    """세그먼트의 고정 adjustment(%) — 격자 해상도(0.1)에 맞춰 반올림."""
    c = centers["by_segment"].get((method, bracket))
    if c is None:
        c = centers["by_method"].get(method, centers["global"])
    return round((c - 1.0) * 100.0, 1)


def optimize_all_pinned(
    records: list[ds.BidRecord],
    risk_model: ReservedRatioModel,
    baseline_params: dict,
    centers: dict,
    year_weights: dict | None = None,
    min_sample: int = MIN_SAMPLE,
    lam: float = DEFAULT_LAMBDA,
    gamma: float = DEFAULT_GAMMA,
    tau: float = DEFAULT_TAU,
    eta: float = DEFAULT_ETA,
    margin_step: float = 0.1,
) -> dict:
    """개선안 최적화 — adj 는 사정률 추정치로 고정, margin 만 격자탐색.

    목적함수·제약·상속 규칙은 `optimize_all` 과 같게 두고 **탐색 축만** 바꾼다.
    비교에서 달라지는 것이 하나여야 원인을 귀속할 수 있다.
    """
    year_weights = year_weights or {}
    new_params: dict = {}
    for method, bracket in ds.iter_segments(records):
        seg = ds.filter_segment(records, method, bracket)
        new_params.setdefault(method, {})
        base_method = baseline_params.get(method, {})
        prev = None
        if bracket in base_method:
            bp = base_method[bracket]
            prev = (float(bp[0]), float(bp[1]))

        adj = pinned_adjustment(centers, method, bracket)

        if len(seg) < min_sample:
            # 희소 세그먼트 — 현행과 같은 상속 규칙. 단 adj 는 추정치로 바꾼다
            # (상속은 '여유분을 물려받는 것'이지 '사정률을 물려받는 것'이 아니다).
            inherited = (
                base_method.get(bracket)
                or base_method.get("medium")
                or baseline_params.get("DEFAULT", {}).get(bracket)
                or [-0.3, 1.0]
            )
            new_params[method][bracket] = [adj, float(inherited[1])]
            continue

        lower_rate = seg[0].lower_limit_rate
        n = len(seg)
        effective_eta = eta * (1.0 + max(0.0, (120 - n) / 60.0))
        baseline_dropout_uw = None
        if prev is not None:
            base_sim = simulate_params(seg, prev[0], prev[1], year_weights)
            baseline_dropout_uw = base_sim.get("dropout_rate_uw", base_sim["dropout_rate"])

        best_margin, best_j = None, -float("inf")
        for margin in pinned_margin_grid(margin_step, adj, lower_rate):
            sim = simulate_params(seg, adj, margin, year_weights)
            if baseline_dropout_uw is not None:
                cand = sim.get("dropout_rate_uw", sim["dropout_rate"])
                if cand > baseline_dropout_uw + SEGMENT_DROPOUT_HARD_LIMIT:
                    continue
            e_drop = risk_model.dropout_probability(adj, margin, method, bracket, lower_rate)
            # η 는 '사이클 간 출렁임 억제'가 목적이므로 이제 margin 축에만 건다.
            j = objective_value(
                sim, e_drop, adj, margin,
                (adj, prev[1]) if prev else None,
                lam, gamma, tau, effective_eta,
            )
            if j > best_j:
                best_j, best_margin = j, margin
        new_params[method][bracket] = [
            adj, best_margin if best_margin is not None else (prev[1] if prev else 1.0)
        ]

    for method, brackets in baseline_params.items():
        new_params.setdefault(method, {})
        for bracket, val in brackets.items():
            if bracket not in new_params[method]:
                new_params[method][bracket] = [
                    pinned_adjustment(centers, method, bracket), float(val[1])
                ]
    return new_params


# ──────────────────────────────────────────────────────────────
# §D 실험 3 — walk-forward 검증
# ──────────────────────────────────────────────────────────────

def run_walkforward(
    records: list[ds.BidRecord],
    active_params: dict,
    holdout_years: tuple[int, ...],
    margin_step: float = 0.1,
) -> dict:
    """연도별 holdout — 학습 연도로 두 방식을 적합하고 미래 연도에서 평가.

    과적합 확인은 BENCHMARK_WIN_REACH.md §3 방식: 학습 성적과 holdout 성적의
    낙폭을 본다. 낙폭이 크면 그 파라미터는 그 연도에만 맞춘 것이다.
    """
    out: dict = {}
    for y in holdout_years:
        train = [r for r in records if r.year < y]
        holdout = [r for r in records if r.year == y]
        if len(train) < 200 or len(holdout) < 50:
            out[str(y)] = {"skipped": "표본 부족", "n_train": len(train), "n_holdout": len(holdout)}
            continue

        yw = None  # 연도 가중은 끈다 — holdout 평가의 공정성을 위해 균등
        rm = ReservedRatioModel.fit(train, yw)
        centers = fit_ratio_centers(train)

        base_params = optimize_all(train, rm, active_params, yw, MIN_SAMPLE)
        prop_params = optimize_all_pinned(
            train, rm, active_params, centers, yw, MIN_SAMPLE, margin_step=margin_step)

        out[str(y)] = {
            "n_train": len(train),
            "n_holdout": len(holdout),
            "train_years": sorted({r.year for r in train}),
            "baseline_refit": {
                "train": tally(train, base_params),
                "holdout": tally(holdout, base_params),
            },
            "proposed_pinned": {
                "train": tally(train, prop_params),
                "holdout": tally(holdout, prop_params),
            },
            "deployed_active": {"holdout": tally(holdout, active_params)},
            "oracle_ratio_mae_holdout": oracle_ratio_mae(holdout),
            "pinned_adjustments": {
                f"{m}/{b}": prop_params[m][b]
                for m in ("적격심사제", "소액수의견적") if m in prop_params
                for b in sorted(prop_params[m])
            },
        }
    return out


def run_segments_static(records: list[ds.BidRecord], active_params: dict) -> dict:
    """정적 데이터에서의 세그먼트별 오차 분해 — 운영 표본 분해와 같은 축.

    운영 모의투찰 표본(2026)은 아직 737공고라 세그먼트를 잘게 자르면 표본이
    바닥난다. 같은 분해를 5개년 4,848건에서도 해 두면 어느 쪽이 표본 노이즈인지
    가릴 수 있다.
    """
    groups: dict = {}
    for r in records:
        groups.setdefault(f"{r.bid_method}/{r.bracket}", []).append(r)
    rows = []
    for seg, recs in sorted(groups.items()):
        if len(recs) < MIN_SAMPLE:
            continue
        t = tally(recs, active_params)
        vals = [r.reserved_ratio for r in recs]
        med = st.median(vals)
        oracle = sum(abs(v - med) for v in vals) / len(vals)
        adj, margin = params_of(active_params, recs[0])
        rows.append({
            "segment": seg,
            "n": len(recs),
            "adjustment": adj,
            "margin": margin,
            "ratio_mae": t["ratio_mae"],
            "ratio_bias": t["ratio_bias"],
            "actual_ratio_median": round(med, 6),
            "actual_ratio_sd": round(st.stdev(vals), 6) if len(vals) > 1 else None,
            "oracle_const_mae": round(oracle, 6),
            "headroom": round(t["ratio_mae"] - oracle, 6),
            "win_rate": t["win_rate"],
            "dropout_rate": t["dropout_rate"],
        })
    return {"by_segment": sorted(rows, key=lambda d: -d["headroom"])}


# ──────────────────────────────────────────────────────────────

def load_static(include_db: bool = False) -> tuple[list[ds.BidRecord], dict]:
    """정적 5개년(+선택적 DB). 금액 기준 불일치 행은 제외하고 **수를 보고한다**.

    제외 수를 연도별로 함께 돌려주는 이유: 2026 은 기초금액 수집이 진행 중이라
    제외율이 과거 연도와 다르다. 합계만 보면 holdout 이 얼마나 걸러진 표본인지
    가려진다(§summarize 가 제외 수를 함께 주는 것과 같은 이유).
    """
    db = None
    if include_db:
        from app.db.session import SessionLocal
        db = SessionLocal()
    try:
        recs = ds.load_records(db=db, strict_db=include_db)
    finally:
        if db is not None:
            db.close()
    kept, per_year = [], {}
    for r in recs:
        y = per_year.setdefault(r.year, {"raw": 0, "kept": 0, "excluded": 0})
        y["raw"] += 1
        if base_is_consistent(r.basic_price, r.reserved_price):
            kept.append(r)
            y["kept"] += 1
        else:
            y["excluded"] += 1
    for y in per_year.values():
        y["excluded_pct"] = round(100.0 * y["excluded"] / y["raw"], 2) if y["raw"] else None
    return kept, {
        "records_raw": len(recs),
        "records_used": len(kept),
        "excluded_base_inconsistent": len(recs) - len(kept),
        "by_year": dict(sorted(per_year.items())),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="사정률 예측 오차 분해·개선안 검증")
    ap.add_argument("--exp", choices=["identifiability", "segments", "walkforward", "all"],
                    default="all")
    ap.add_argument("--include-db", action="store_true",
                    help="운영 DB 의 누적 개찰결과를 병합(SELECT 만)")
    ap.add_argument("--holdout-years", default="2022,2023,2024,2025")
    ap.add_argument("--margin-step", type=float, default=0.1,
                    help="개선안 margin 격자 간격 (현행 2축 격자와 해상도 대조용)")
    ap.add_argument("--json-out", default=str(RESULTS_PATH))
    args = ap.parse_args()

    records, accounting = load_static(include_db=args.include_db)
    active = get_default_store().load_active()

    result: dict = {
        "generated_for": "docs/MOCK_BIDDING_DESIGN.md §0.2 4차 지표",
        "data": {
            **accounting,
            "base_ratio_band": [BASE_RATIO_MIN, BASE_RATIO_MAX],
            "include_db": args.include_db,
            "years": sorted({r.year for r in records}),
        },
        "active_version": active.version_id,
    }

    if args.exp in ("identifiability", "all"):
        result["identifiability"] = run_identifiability(records, active.params)
    if args.exp in ("segments", "all"):
        result["segments_static"] = run_segments_static(records, active.params)
    if args.exp in ("walkforward", "all"):
        years = tuple(int(y) for y in args.holdout_years.split(",") if y.strip())
        result["walkforward"] = run_walkforward(
            records, active.params, years, margin_step=args.margin_step)
        result["margin_step"] = args.margin_step

    Path(args.json_out).write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\n[saved] {args.json_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
