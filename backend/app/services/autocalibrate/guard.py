"""
regression 가드 (특허 신규성 핵심)
====================================
자가보정 루프가 자동으로 파라미터를 바꿀 때, 새 후보가 직전 운영본보다
나쁘면 **자동 거부·롤백**한다. 자동화에 따른 성능 퇴행을 구조적으로 차단.

가드 게이트 (모두 통과해야 채택):
  ① dropout_rate  — 직전 대비 개선 또는 동일 필수 (1차 목표)
  ② win_rate      — 직전 대비 −허용폭 이내
  ③ rate_error    — 직전 대비 악화폭 제한
  ④ walk-forward  — 최근 연도 hold-out 에서도 탈락률 개선
  ⑤ 세그먼트 안전 — 어떤 세그먼트도 탈락률이 크게 악화되지 않음
  ⑥ 변화량 상한  — 파라미터가 직전 대비 과도하게 점프하지 않음

거부 시 active 불변 = 자동 롤백.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.autocalibrate import dataset as ds
from app.services.autocalibrate.optimizer import evaluate_params

# 가드 임계값
MAX_WINRATE_LOSS = 0.5          # 낙찰률 허용 손실 (%p)
MAX_RATE_ERROR_INCREASE = 0.1   # 사정률 오차 허용 악화 (%p)
MAX_HOLDOUT_DROPOUT_INCREASE = 0.5  # hold-out 탈락률 허용 악화 (%p)
MAX_SEGMENT_DROPOUT_INCREASE = 2.0  # 세그먼트별 탈락률 허용 악화 (%p)
MAX_PARAM_JUMP = 1.0            # 파라미터 1회 변화 상한 (adj %, margin %p)


@dataclass
class GuardDecision:
    """가드 판정 결과."""

    accepted: bool
    reasons: list[str]
    metric_deltas: dict           # baseline 대비 변화량
    insample_metrics: dict        # 후보의 전체 지표
    baseline_metrics: dict        # 기준선의 전체 지표
    holdout_metrics: dict = field(default_factory=dict)
    baseline_holdout: dict = field(default_factory=dict)


def _segment_dropout(records: list, params: dict) -> dict:
    """세그먼트별 탈락률 (%) — 세그먼트 안전성 검사용."""
    out: dict = {}
    for method, bracket in ds.iter_segments(records):
        seg = ds.filter_segment(records, method, bracket)
        if not seg:
            continue
        m = evaluate_params(seg, params)
        out[f"{method}/{bracket}"] = m["dropout_rate"]
    return out


def evaluate_candidate(
    candidate_params: dict,
    baseline_params: dict,
    records: list,
    holdout_years: tuple[int, ...] = (2025, 2026),
) -> GuardDecision:
    """후보 파라미터셋을 기준선과 비교해 채택 여부 판정."""
    reasons: list[str] = []
    accepted = True

    # in-sample 전체 백테스트
    cand = evaluate_params(records, candidate_params)
    base = evaluate_params(records, baseline_params)

    # walk-forward: hold-out 분리
    _, holdout = ds.split_by_year(records, holdout_years)
    cand_ho = evaluate_params(holdout, candidate_params) if holdout else {}
    base_ho = evaluate_params(holdout, baseline_params) if holdout else {}

    # ── 게이트 ① dropout_rate 개선 필수 ──────────────────────
    if cand["dropout_rate"] > base["dropout_rate"] + 1e-6:
        accepted = False
        reasons.append(
            f"✗ 탈락률 악화: {base['dropout_rate']}% → {cand['dropout_rate']}%"
        )
    else:
        reasons.append(
            f"✓ 탈락률 개선: {base['dropout_rate']}% → {cand['dropout_rate']}%"
        )

    # ── 게이트 ② win_rate 손실 제한 ─────────────────────────
    winrate_loss = base["win_rate"] - cand["win_rate"]
    if winrate_loss > MAX_WINRATE_LOSS:
        accepted = False
        reasons.append(
            f"✗ 낙찰률 과도 손실: -{winrate_loss:.2f}%p (허용 {MAX_WINRATE_LOSS}%p)"
        )
    else:
        reasons.append(
            f"✓ 낙찰률 변화: {cand['win_rate'] - base['win_rate']:+.2f}%p"
        )

    # ── 게이트 ③ rate_error 악화 제한 ───────────────────────
    rate_err_delta = cand["rate_error"] - base["rate_error"]
    if rate_err_delta > MAX_RATE_ERROR_INCREASE:
        accepted = False
        reasons.append(
            f"✗ 사정률 오차 악화: {base['rate_error']} → {cand['rate_error']}"
        )

    # ── 게이트 ④ walk-forward hold-out 검증 ─────────────────
    if holdout:
        ho_delta = cand_ho.get("dropout_rate", 0) - base_ho.get("dropout_rate", 0)
        if ho_delta > MAX_HOLDOUT_DROPOUT_INCREASE:
            accepted = False
            reasons.append(
                f"✗ hold-out({holdout_years}) 탈락률 악화: "
                f"{base_ho.get('dropout_rate')}% → {cand_ho.get('dropout_rate')}%"
            )
        else:
            reasons.append(
                f"✓ hold-out 탈락률: {base_ho.get('dropout_rate')}% → "
                f"{cand_ho.get('dropout_rate')}%"
            )

    # ── 게이트 ⑤ 세그먼트 안전성 ────────────────────────────
    cand_seg = _segment_dropout(records, candidate_params)
    base_seg = _segment_dropout(records, baseline_params)
    unsafe = []
    for seg, cand_dr in cand_seg.items():
        base_dr = base_seg.get(seg, cand_dr)
        if cand_dr > base_dr + MAX_SEGMENT_DROPOUT_INCREASE:
            unsafe.append(f"{seg} ({base_dr}%→{cand_dr}%)")
    if unsafe:
        accepted = False
        reasons.append(f"✗ 세그먼트 탈락률 악화: {', '.join(unsafe)}")

    # ── 게이트 ⑥ 파라미터 변화량 상한 ───────────────────────
    big_jumps = []
    for method, brackets in candidate_params.items():
        for bracket, cv in brackets.items():
            bv = baseline_params.get(method, {}).get(bracket)
            if not bv:
                continue
            d_adj = abs(float(cv[0]) - float(bv[0]))
            d_margin = abs(float(cv[1]) - float(bv[1]))
            if d_adj > MAX_PARAM_JUMP or d_margin > MAX_PARAM_JUMP:
                big_jumps.append(
                    f"{method}/{bracket} (Δadj={d_adj:.1f}, Δmargin={d_margin:.1f})"
                )
    if big_jumps:
        accepted = False
        reasons.append(f"✗ 파라미터 급변: {', '.join(big_jumps)}")

    if accepted:
        reasons.append("→ 모든 게이트 통과: 채택")
    else:
        reasons.append("→ 게이트 실패: 거부 (active 불변 = 자동 롤백)")

    return GuardDecision(
        accepted=accepted,
        reasons=reasons,
        metric_deltas={
            "win_rate": round(cand["win_rate"] - base["win_rate"], 3),
            "dropout_rate": round(cand["dropout_rate"] - base["dropout_rate"], 3),
            "rate_error": round(rate_err_delta, 4),
        },
        insample_metrics=cand,
        baseline_metrics=base,
        holdout_metrics=cand_ho,
        baseline_holdout=base_ho,
    )
