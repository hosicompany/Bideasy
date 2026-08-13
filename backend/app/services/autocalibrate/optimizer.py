"""
위험제약 최적화 (특허 신규성 핵심)
====================================
기존 optimize_weighted.py 의 "pass_rate >= 90% 하드 제약 → win_rate 최대화"를
**위험 명시 목적함수**로 재설계.

위험 명시 목적함수 (세그먼트 s, 파라미터 θ=(adjustment, margin)):

  J(θ,s) = WinRate(θ,s)
           − λ·E[Dropout(θ,s)]                 # 연속 위험 패널티
           − γ·max(0, E[Dropout(θ,s)] − τ)²    # 목표(τ) 초과분 2차 패널티
           − η·‖θ − θ_prev‖²                   # 변화 억제 정규화 (루프 안정성)

- E[Dropout] 은 risk_model 의 해석적 탈락확률 (임계값이 아닌 연속량)
- τ = 목표 탈락률 → 1차 목표(탈락 8.6% 인하) 달성 경로
- θ_prev 정규화 → 데이터 노이즈로 파라미터가 매 사이클 출렁이는 것 방지

신규성 3: adaptive_year_weights — 고정 연도 가중치 대신 시장 변동성을
측정해 가중 기울기를 데이터가 스스로 결정.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.services.autocalibrate.dataset import (
    BidRecord,
    filter_segment,
    iter_segments,
)
from app.services.autocalibrate.risk_model import ReservedRatioModel

# ── 목적함수 하이퍼파라미터 (Phase 5 에서 dry-run 튜닝) ──────
# win_rate(0~1)와 E[dropout](0~1)이 비슷한 스케일이라 λ가 크면 위험회피 과치우침.
# τ 미만 구간은 약하게(λ), τ 초과 구간은 강하게(γ) 패널티 → 1차 목표(탈락 인하)는
# γ가 담당하고 그 안에서는 win_rate 최대화.
DEFAULT_LAMBDA = 0.5   # 연속 위험 패널티 계수 (Phase 1: 0.3 → 0.5)
DEFAULT_GAMMA = 50.0   # 목표 초과분 2차 패널티 계수 (Phase 1: 8.0 → 50.0)
DEFAULT_TAU = 0.05     # 목표 탈락률 (1차 목표 = 5%; Phase 1: 0.07 → 0.05)
DEFAULT_ETA = 0.04     # 변화 억제 정규화 계수
# Phase 1 그리드탐색(2026-05-27)에서 (0.5, 50, 0.05) 조합이 1차 목표 5% 거의
# 달성 + 낙찰률 손실 1%p 이내 + 사정률 오차 임계값 내에서 가장 균형 잡힌
# Pareto 최적점으로 확인됨. 이전 (0.3, 8.0, 0.07) 은 탈락 7.49% 로 정체.

# 그리드서치 범위 (기존 optimize_weighted.py 와 동일)
_ADJ_RANGE = [x / 10 for x in range(-10, 16)]      # -1.0 ~ 1.5
_MARGIN_RANGE = [x / 10 for x in range(0, 16)]     # 0.0 ~ 1.5

# 세그먼트 안전 제약 — baseline 대비 세그먼트 탈락률(균등)이 이 값 이상
# 악화되는 후보는 그리드서치에서 제외 (guard 의 세그먼트 안전성과 일관).
SEGMENT_DROPOUT_HARD_LIMIT = 1.5  # %p


@dataclass
class CandidateParams:
    """한 세그먼트의 최적화 결과."""

    method: str
    bracket: str
    adjustment: float
    margin: float
    objective: float
    win_rate: float           # 가중 시뮬레이션 낙찰률 (%)
    pass_rate: float          # 가중 시뮬레이션 통과율 (%)
    expected_dropout: float   # risk_model 기대 탈락확률 (0~1)
    n_samples: int
    source: str = "optimized"  # "optimized" | "inherited"
    # 4번 확장 대비 — 블루오션 의사결정 신호 등 추가 슬롯
    features: dict = field(default_factory=dict)


def simulate_params(
    records: list[BidRecord],
    adjustment: float,
    margin: float,
    year_weights: dict[int, float] | None = None,
) -> dict:
    """한 파라미터 조합 (adj, margin)으로 가중 win/pass 시뮬레이션.

    레코드별 lower_limit_rate 를 사용 (공사 87.745, 용역 60 등 차등 반영).
    """
    year_weights = year_weights or {}
    win_w = pass_w = total_w = 0.0      # 연도 가중 (최근 트렌드 반영 — win_rate 용)
    pass_u = total_u = 0                # 균등 (보수적 — 탈락 위험 용)
    for r in records:
        w = year_weights.get(r.year, 1.0)
        total_w += w
        total_u += 1
        predicted = r.basic_price * (1 + adjustment / 100.0)
        target_rate = r.lower_limit_rate + margin
        target_price = math.floor(predicted * target_rate / 100.0 / 10) * 10
        lower_limit = r.reserved_price * r.lower_limit_rate / 100.0
        if target_price >= lower_limit:
            pass_w += w
            pass_u += 1
            if target_price <= r.winner_price:
                win_w += w
    if total_w <= 0:
        return {
            "win_rate": 0.0, "pass_rate": 0.0,
            "dropout_rate": 0.0, "dropout_rate_uw": 0.0,
        }
    return {
        "win_rate": win_w / total_w * 100.0,                       # 연도 가중
        "pass_rate": pass_w / total_w * 100.0,                     # 연도 가중
        "dropout_rate": (total_w - pass_w) / total_w * 100.0,      # 연도 가중
        # 균등 가중 탈락률 — 어느 시기든 탈락은 위험하므로 보수적으로 평가.
        # optimizer 가 최근 데이터에만 최적화해 과거에서 나빠지는 것 방지.
        "dropout_rate_uw": (total_u - pass_u) / total_u * 100.0 if total_u else 0.0,
    }


def objective_value(
    sim: dict,
    expected_dropout: float,
    adjustment: float,
    margin: float,
    prev_params: tuple[float, float] | None,
    lam: float,
    gamma: float,
    tau: float,
    eta: float,
) -> float:
    """위험 명시 목적함수 J 계산.

    탈락 위험은 risk_model 의 해석적 예측(일반화에 강함)과
    세그먼트 실측 탈락률(해당 세그먼트에 정확) 중 **보수적으로 큰 값**을 사용.
    → 표본 적은 세그먼트에서 risk_model 이 위험을 과소평가해도 실측이 방어.
    """
    win_rate = sim["win_rate"] / 100.0  # 0~1 정규화 (연도 가중 — 최근 트렌드)
    # 탈락 위험은 균등 가중 실측을 사용 (어느 시기든 탈락은 위험)
    sim_dropout = sim.get("dropout_rate_uw", sim["dropout_rate"]) / 100.0
    effective_dropout = max(expected_dropout, sim_dropout)  # 보수적
    excess = max(0.0, effective_dropout - tau)
    j = win_rate - lam * effective_dropout - gamma * excess**2
    if prev_params is not None:
        d_adj = adjustment - prev_params[0]
        d_margin = margin - prev_params[1]
        j -= eta * (d_adj**2 + d_margin**2)
    return j


PARAMETRIZATION = "ratio_pinned_v2"
_MARGIN_STEP = 0.1


def pinned_adjustment(risk_model: ReservedRatioModel, method: str, bracket: str) -> float:
    """사정률 중심(중앙값)을 `adjustment` 로 환산 — 탐색하지 않고 고정한다.

    MAE 의 최적 점예측은 평균이 아니라 중앙값이고, 얕은 세그먼트의 부모
    shrinkage 는 `risk_model.get_segment` 계약을 그대로 따른다.

    저장·표시 형식이 0.1 단위라 같은 해상도로 반올림한다 — 사정률 σ 가 약
    0.8%p 라 0.1%p 손실은 무시 가능하고, 2자리로 두면 화면(`{adj:+.1f}%`)이
    실제와 다른 숫자를 보여준다.
    """
    return round((risk_model.predict_reserved_ratio(method, bracket) - 1.0) * 100, 1)


def margin_grid(lower_rate: float, adjustment: float, step: float = _MARGIN_STEP) -> list[float]:
    """고정된 adjustment 에서 곱의 도달 범위를 보존하는 margin 격자.

    ⚠️ 상한을 상수로 박으면 **고정값에 따라 한쪽이 조용히 잘린다** — adjustment
    가 음수로 고정되면 같은 곱에 닿는 데 더 큰 margin 이 필요한데, 옛 상한
    (1.5%p) 을 그대로 쓰면 공격적인 쪽 후보가 격자에서 사라진다. 탐색 축을
    줄이면서 도달 범위까지 줄이면 성능 변화의 원인을 귀속할 수 없다.

    그래서 2축 격자가 닿던 **곱의 최대치**를 고정 adjustment 에서 재현하는
    지점까지 상한을 유도한다. 하한은 0.0 을 유지한다 — 하한율 미만은 정의상
    무효라 탐색할 이유가 없다(옛 격자의 음수 곱 영역은 애초에 사표였다).
    """
    scale = 1.0 + adjustment / 100.0
    max_product = (1.0 + max(_ADJ_RANGE) / 100.0) * (lower_rate + max(_MARGIN_RANGE))
    upper = max_product / scale - lower_rate if scale > 0 else max(_MARGIN_RANGE)
    # 내림하면 격자가 목표 곱에 **못 미치는** 지점에서 끝난다(반올림 손실이
    # 곧 잘림이다). 올림이면 최대 한 칸 넘칠 뿐이라 커버리지가 보장된다.
    steps = max(1, math.ceil(upper / step - 1e-9))
    return [round(i * step, 2) for i in range(steps + 1)]


def converted_margin(
    lower_rate: float, old_adj: float, old_margin: float, new_adj: float
) -> float:
    """파라미터화 전환 시 곱을 보존하는 margin (전환 스크립트가 쓴다).

    격자 해상도(0.1%p)라 곱이 정확히 같을 수는 없는데, **반올림 방향이 곧 위험
    방향이다** — 곱이 줄면 투찰가가 낮아져 낙찰하한선에 가까워지고 무효 위험이
    커진다(무효율은 §0.2 1차 지표). 반올림하면 세그먼트 절반이 그쪽으로
    떨어지므로 잔차를 **항상 안전한 쪽(곱 ≥ 기존)** 으로 몰아 올림한다.

    margin 은 0.0 미만이 될 수 없다 — 하한율 아래는 정의상 무효다. 사정률
    중심이 크게 잡힌 세그먼트에서 곱을 맞추려다 음수가 나올 수 있는데(실측:
    실시설계기술제안입찰/xxlarge), 그때는 곱 보존을 포기하고 0.0 으로 막는다.
    그 세그먼트도 곱이 커지므로 역시 안전한 쪽이다.
    """
    old_product = (1.0 + old_adj / 100.0) * (lower_rate + old_margin)
    exact = old_product / (1.0 + new_adj / 100.0) - lower_rate
    return max(0.0, math.ceil(exact * 10 - 1e-9) / 10)


def optimize_segment(
    records: list[BidRecord],
    method: str,
    bracket: str,
    risk_model: ReservedRatioModel,
    prev_params: tuple[float, float] | None = None,
    year_weights: dict[int, float] | None = None,
    lam: float = DEFAULT_LAMBDA,
    gamma: float = DEFAULT_GAMMA,
    tau: float = DEFAULT_TAU,
    eta: float = DEFAULT_ETA,
) -> CandidateParams | None:
    """세그먼트별 위험제약 그리드서치."""
    seg_records = filter_segment(records, method, bracket)
    if not seg_records:
        return None
    lower_rate = seg_records[0].lower_limit_rate

    # 희소 세그먼트일수록 변화 억제(η)를 강화 — 베이지안 안정화 (신규성 4).
    # 표본이 적으면 risk_model 예측 신뢰도가 낮으므로 baseline 근처에 머무름.
    n = len(seg_records)
    effective_eta = eta * (1.0 + max(0.0, (120 - n) / 60.0))

    # 세그먼트 안전 제약: baseline 대비 탈락률(균등)이 크게 악화되는 후보는 제외.
    # guard 의 세그먼트 안전성 게이트를 optimizer 가 미리 만족하도록.
    baseline_dropout_uw: float | None = None
    if prev_params is not None:
        base_sim = simulate_params(
            seg_records, prev_params[0], prev_params[1], year_weights
        )
        baseline_dropout_uw = base_sim.get("dropout_rate_uw", base_sim["dropout_rate"])

    # ── 탐색 축: margin 1축 (adjustment 는 데이터에서 고정) ──────────
    # 옛 2축 탐색은 J 가 (adj, margin) 을 **곱으로만** 보는 탓에 adjustment 를
    # 식별하지 못했다 — 곱이 같은 조합은 목적함수가 동일해서, 최적화가 고른
    # adjustment 는 사정률 예측이 아니라 margin 과의 임의 배분이었다.
    # 그 부산물이 ① 4차 지표 오염 ② A값 가격식에서의 실제 가격 차이로 샜다.
    # 상세·검증 = docs/MOCK_BIDDING_DESIGN.md §9 (2026-08-13).
    adj = pinned_adjustment(risk_model, method, bracket)

    best: CandidateParams | None = None
    best_j = -float("inf")
    for margin in margin_grid(lower_rate, adj):
        sim = simulate_params(seg_records, adj, margin, year_weights)
        # 세그먼트 안전 제약 (hard)
        if baseline_dropout_uw is not None:
            cand_dropout_uw = sim.get("dropout_rate_uw", sim["dropout_rate"])
            if cand_dropout_uw > baseline_dropout_uw + SEGMENT_DROPOUT_HARD_LIMIT:
                continue
        e_dropout = risk_model.dropout_probability(
            adj, margin, method, bracket, lower_rate
        )
        j = objective_value(
            sim, e_dropout, adj, margin, prev_params, lam, gamma, tau, effective_eta
        )
        if j > best_j:
            best_j = j
            best = CandidateParams(
                method=method,
                bracket=bracket,
                adjustment=adj,
                margin=margin,
                objective=round(j, 6),
                win_rate=round(sim["win_rate"], 3),
                pass_rate=round(sim["pass_rate"], 3),
                expected_dropout=round(e_dropout, 5),
                n_samples=len(seg_records),
                source="optimized",
            )
    return best


def optimize_all(
    records: list[BidRecord],
    risk_model: ReservedRatioModel,
    baseline_params: dict,
    year_weights: dict[int, float] | None = None,
    min_sample: int = 10,
    **objective_kwargs,
) -> dict:
    """모든 세그먼트 최적화 → 새 파라미터 딕셔너리 생성.

    표본 부족 세그먼트는 baseline 또는 부모(같은 입찰방법의 medium) 상속.
    """
    new_params: dict = {}
    segments = iter_segments(records)

    for method, bracket in segments:
        seg_records = filter_segment(records, method, bracket)
        new_params.setdefault(method, {})

        prev = None
        base_method = baseline_params.get(method, {})
        if bracket in base_method:
            bp = base_method[bracket]
            prev = (float(bp[0]), float(bp[1]))

        if len(seg_records) < min_sample:
            # 희소 세그먼트 — baseline 상속 (없으면 medium → DEFAULT)
            inherited = (
                base_method.get(bracket)
                or base_method.get("medium")
                or baseline_params.get("DEFAULT", {}).get(bracket)
                or [-0.3, 1.0]
            )
            new_params[method][bracket] = [float(inherited[0]), float(inherited[1])]
            continue

        result = optimize_segment(
            records, method, bracket, risk_model,
            prev_params=prev, year_weights=year_weights, **objective_kwargs,
        )
        if result is None:
            new_params[method][bracket] = list(prev) if prev else [-0.3, 1.0]
        else:
            new_params[method][bracket] = [result.adjustment, result.margin]

    # baseline 에만 있고 데이터엔 없는 세그먼트(예: DEFAULT) 보존
    for method, brackets in baseline_params.items():
        new_params.setdefault(method, {})
        for bracket, val in brackets.items():
            if bracket not in new_params[method]:
                new_params[method][bracket] = [float(val[0]), float(val[1])]

    return new_params


def evaluate_params(
    records: list[BidRecord],
    params: dict,
    year_weights: dict[int, float] | None = None,
) -> dict:
    """전체 레코드에 파라미터셋 적용 → 종합 지표 (guard / loop 공유).

    mock_bidding_test.backtest 와 동일 공식이지만 details 없이 지표만 (경량).
    """
    year_weights = year_weights or {}
    win_w = pass_w = total_w = 0.0
    rate_errors: list[float] = []
    for r in records:
        w = year_weights.get(r.year, 1.0)
        total_w += w
        mp = params.get(r.bid_method, params.get("DEFAULT", {}))
        p = mp.get(r.bracket) or params.get("DEFAULT", {}).get(r.bracket, [-0.3, 1.0])
        adj, margin = float(p[0]), float(p[1])
        predicted = r.basic_price * (1 + adj / 100.0)
        target_rate = r.lower_limit_rate + margin
        target_price = math.floor(predicted * target_rate / 100.0 / 10) * 10
        lower_limit = r.reserved_price * r.lower_limit_rate / 100.0
        our_rate = (target_price / r.basic_price * 100.0) if r.basic_price > 0 else 0.0
        if r.winner_rate > 0:
            rate_errors.append(abs(our_rate - r.winner_rate))
        if target_price >= lower_limit:
            pass_w += w
            if target_price <= r.winner_price:
                win_w += w
    n = len(records)
    return {
        "total": n,
        "win_rate": round(win_w / total_w * 100.0, 3) if total_w else 0.0,
        "pass_rate": round(pass_w / total_w * 100.0, 3) if total_w else 0.0,
        "dropout_rate": round((total_w - pass_w) / total_w * 100.0, 3) if total_w else 0.0,
        "rate_error": round(sum(rate_errors) / len(rate_errors), 4) if rate_errors else 0.0,
    }


def adaptive_year_weights(records: list[BidRecord]) -> dict[int, float]:
    """시장 변동성 감응 적응형 시간 가중 (특허 신규성 3).

    최근 연도의 사정비율 분포가 과거 대비 얼마나 벗어났는지(z-score 유사)를
    측정해, 가중 기울기를 데이터가 스스로 결정한다.
    - 시장 급변기 → 최근 데이터에 집중 (기울기 ↑, 최대 4x)
    - 안정기     → 과거도 고르게 반영 (기울기 평탄, 1x 근처)
    """
    by_year: dict[int, list[float]] = {}
    for r in records:
        if r.reserved_ratio > 0:
            by_year.setdefault(r.year, []).append(r.reserved_ratio)
    years = sorted(by_year)
    if len(years) < 2:
        return {y: 1.0 for y in years}

    year_mu = {y: sum(v) / len(v) for y, v in by_year.items()}
    recent = years[-1]
    past_years = years[:-1]
    past_mu = sum(year_mu[y] for y in past_years) / len(past_years)
    past_vals = [year_mu[y] for y in past_years]
    past_std = math.sqrt(
        sum((m - past_mu) ** 2 for m in past_vals) / len(past_vals)
    ) or 1e-4

    # 최근 연도가 과거 평균에서 벗어난 정도
    drift = abs(year_mu[recent] - past_mu) / past_std
    slope = min(4.0, 1.0 + drift)  # 1x ~ 4x

    n = len(years)
    weights: dict[int, float] = {}
    for i, y in enumerate(years):
        rank = i / (n - 1)  # 0 (최고 과거) ~ 1 (최근)
        weights[y] = round(1.0 + (slope - 1.0) * rank, 4)
    return weights
