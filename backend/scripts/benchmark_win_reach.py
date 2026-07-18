"""
낙찰 도달 성능 벤치마크 (Win-Reach Benchmark)
=============================================
"낙찰은 최종 목표 — 타사와 동등 이상 가능한가?"를 우리 개찰 데이터로 실측.

지표·게이트는 docs/BENCHMARK_WIN_REACH.md §0 에 사전 등록(동결)됨.
프로덕션 코드 0줄 변경 — autocalibrate 모듈을 임포트만 한다.

실험:
  audit    — 데이터 감사 + active v20260527 기준선 재현(±0.5%p, 실패 시 exit 1)
  policies — 3정책(standard -2.5 / active / aggressive -12) 킬러윈도우 적중률
  oracle   — 사후 최적 단일 투찰률 상한 + walk-forward 과적합 정량화 + 모델 상한
  frontier — 목적함수 반전(낙찰 최대화, dropout 캡별) 안전-낙찰 프론티어

사용:
  python scripts/benchmark_win_reach.py --exp all
  python scripts/benchmark_win_reach.py --exp audit --quick
  python scripts/benchmark_win_reach.py --exp frontier --wide
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

# Windows 콘솔 한글 깨짐 방지 (mock_bidding_test.py 패턴)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.autocalibrate import dataset as ds                    # noqa: E402
from app.services.autocalibrate.optimizer import (                      # noqa: E402
    evaluate_params,
    simulate_params,
)
from app.services.autocalibrate.risk_model import ReservedRatioModel    # noqa: E402
from app.services.autocalibrate.strategy_store import get_default_store  # noqa: E402

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTS_PATH = DATA_DIR / "benchmark_win_reach_results.json"

# 그리드 범위 — optimizer.py:47-48 (_ADJ_RANGE/_MARGIN_RANGE) 와 동일 값 복제.
# private 상수라 임포트 대신 복제하고 출처를 명시한다.
GRID_ADJ = [x / 10 for x in range(-10, 16)]       # -1.0 ~ 1.5
GRID_MARGIN = [x / 10 for x in range(0, 16)]      # 0.0 ~ 1.5
WIDE_ADJ = [x / 10 for x in range(-30, 31)]       # -3.0 ~ 3.0
WIDE_MARGIN = [x / 10 for x in range(0, 31)]      # 0.0 ~ 3.0

DROPOUT_CAPS = [2.0, 3.0, 4.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0, None]
MIN_SAMPLE = 10           # optimizer.optimize_all 과 동일한 희소 세그먼트 기준
HOLDOUT_YEARS = (2025,)
BASELINE_TOLERANCE = 0.5  # %p — audit 기준선 재현 허용 오차 (사전 등록 부칙 3)


# ──────────────────────────────────────────────────────────────
# §A 공통 인프라
# ──────────────────────────────────────────────────────────────

def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """이항 비율의 Wilson 95% 신뢰구간 (%)."""
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half) * 100.0, min(1.0, center + half) * 100.0)


def interval_of(r: ds.BidRecord) -> tuple[float, float] | None:
    """낙찰 가능 투찰률 구간 [L, U] (기초금액 대비 %). None = 낙찰 불가능(역전).

    L = 실제 하한선 비율 = reserved_ratio × lower_limit_rate
    U = 실제 낙찰가 비율 + 10원 절사 여유(1000/basic_price %p)
    """
    if r.basic_price <= 0:
        return None
    L = r.reserved_ratio * r.lower_limit_rate
    U = r.winner_price / r.basic_price * 100.0 + 1000.0 / r.basic_price
    if U < L:
        return None
    return (L, U)


def floor_price(r: ds.BidRecord) -> float:
    """실제 하한선 금액 (evaluate_params 와 동일 공식)."""
    return r.reserved_price * r.lower_limit_rate / 100.0


def judge(r: ds.BidRecord, price: int) -> str:
    """WIN / DROPOUT / LOST — simulate_params(optimizer.py:94-98) 정의와 동일."""
    if price < floor_price(r):
        return "DROPOUT"
    if price <= r.winner_price:
        return "WIN"
    return "LOST"


def price_flat(r: ds.BidRecord, rate_pct: float) -> int:
    """사정률 정책 가격 = 기초금액×(1+rate/100), 10원 절사.

    calculator.calculate_safe_bid(a_value=0) 와 동일 공식.
    """
    return math.floor(r.basic_price * (1 + rate_pct / 100.0) / 10) * 10


def price_params(r: ds.BidRecord, params: dict) -> int:
    """전략 파라미터셋 가격 — evaluate_params(optimizer.py:279-284) 공식 그대로."""
    mp = params.get(r.bid_method, params.get("DEFAULT", {}))
    p = mp.get(r.bracket) or params.get("DEFAULT", {}).get(r.bracket, [-0.3, 1.0])
    adj, margin = float(p[0]), float(p[1])
    predicted = r.basic_price * (1 + adj / 100.0)
    target_rate = r.lower_limit_rate + margin
    return math.floor(predicted * target_rate / 100.0 / 10) * 10


def tally(records: list[ds.BidRecord], price_fn) -> dict:
    """정책 한 개의 win/dropout/lost 집계 + Wilson CI."""
    win = drop = 0
    for r in records:
        v = judge(r, price_fn(r))
        if v == "WIN":
            win += 1
        elif v == "DROPOUT":
            drop += 1
    n = len(records)
    lost = n - win - drop
    lo, hi = wilson_ci(win, n)
    return {
        "n": n,
        "win_rate": round(win / n * 100.0, 3) if n else 0.0,
        "dropout_rate": round(drop / n * 100.0, 3) if n else 0.0,
        "lost_rate": round(lost / n * 100.0, 3) if n else 0.0,
        "win_ci95": [round(lo, 3), round(hi, 3)],
    }


def slice_report(records: list[ds.BidRecord], price_fn) -> dict:
    """전체 / 연도별 / 세그먼트별 집계."""
    by_year: dict[int, list] = {}
    by_seg: dict[str, list] = {}
    for r in records:
        by_year.setdefault(r.year, []).append(r)
        by_seg.setdefault(f"{r.bid_method}/{r.bracket}", []).append(r)
    return {
        "overall": tally(records, price_fn),
        "by_year": {str(y): tally(rs, price_fn) for y, rs in sorted(by_year.items())},
        "by_segment": {
            seg: tally(rs, price_fn)
            for seg, rs in sorted(by_seg.items())
            if len(rs) >= MIN_SAMPLE
        },
    }


def dedup_records(records: list[ds.BidRecord]) -> tuple[list[ds.BidRecord], int]:
    """bid_no 중복(재입찰 차수) 제거 — 마지막 항목(최신 차수) 유지."""
    seen: dict[str, ds.BidRecord] = {}
    for r in records:
        seen[r.bid_no] = r  # 뒤가 이김 (파일 순서 = 차수 순서)
    deduped = list(seen.values())
    return deduped, len(records) - len(deduped)


def load_all() -> tuple[list[ds.BidRecord], list[ds.BidRecord], int]:
    """(원본, dedup본, 중복수). 기준선 재현은 원본으로, 실험은 dedup본으로."""
    raw = ds.load_records(db=None)
    deduped, n_dup = dedup_records(raw)
    return raw, deduped, n_dup


def quick_sample(records: list[ds.BidRecord], step: int = 10) -> list[ds.BidRecord]:
    """--quick 스모크용 결정적 표본 (연도 분포 유지를 위해 등간 추출)."""
    return records[::step]


# ──────────────────────────────────────────────────────────────
# §B 실험 0 — 데이터 감사
# ──────────────────────────────────────────────────────────────

def run_audit(raw: list[ds.BidRecord], deduped: list[ds.BidRecord], n_dup: int) -> dict:
    print("\n=== [audit] 데이터 감사 ===")

    # 1) 원본 JSON 스캔 — llr 결측률 (dataset 은 87.745 폴백하므로 원본에서 세야 함)
    raw_items = 0
    llr_missing = 0
    for year in range(2021, 2027):
        f = DATA_DIR / f"opening_results_{year}.json"
        if not f.exists():
            continue
        with open(f, encoding="utf-8") as fh:
            items = json.load(fh)
        for item in items:
            raw_items += 1
            if not item.get("lower_limit_rate"):
                llr_missing += 1

    # 2) llr 값 분포 (로드 후)
    llr_counts: dict[float, int] = {}
    for r in raw:
        llr_counts[r.lower_limit_rate] = llr_counts.get(r.lower_limit_rate, 0) + 1
    llr_top = sorted(llr_counts.items(), key=lambda kv: -kv[1])[:5]

    # 3) winner_rate 필드 vs 직접 계산 괴리
    diff_gt_005 = diff_gt_05 = 0
    max_diff = 0.0
    n_rate = 0
    for r in raw:
        if r.winner_rate > 0 and r.basic_price > 0:
            n_rate += 1
            computed = r.winner_price / r.basic_price * 100.0
            d = abs(r.winner_rate - computed)
            max_diff = max(max_diff, d)
            if d > 0.05:
                diff_gt_005 += 1
            if d > 0.5:
                diff_gt_05 += 1

    # 4) 역전 인터벌 (낙찰가 < 하한선 — 이상 데이터)
    inverted = sum(1 for r in deduped if interval_of(r) is None)

    # 5) 기준선 재현 — active 파라미터를 원본(비dedup)에 적용, 저장 지표와 대조
    store = get_default_store()
    active = store.load_active()
    repro = evaluate_params(raw, active.params)  # 균등 가중 (guard.py:73 과 동일)
    stored = active.metrics
    deltas = {
        k: round(abs(repro[k] - stored.get(k, 0.0)), 3)
        for k in ("win_rate", "pass_rate", "dropout_rate")
    }
    repro_ok = all(v <= BASELINE_TOLERANCE for v in deltas.values())

    year_counts: dict[int, int] = {}
    for r in raw:
        year_counts[r.year] = year_counts.get(r.year, 0) + 1

    out = {
        "raw_json_items": raw_items,
        "loaded_records": len(raw),
        "deduped_records": len(deduped),
        "duplicate_bid_no": n_dup,
        "by_year_counts": {str(y): c for y, c in sorted(year_counts.items())},
        "llr_missing_in_raw_json": llr_missing,
        "llr_missing_pct": round(llr_missing / raw_items * 100.0, 2) if raw_items else 0.0,
        "llr_top_values": [[v, c] for v, c in llr_top],
        "winner_rate_field_check": {
            "n": n_rate,
            "diff_gt_0.05pct": diff_gt_005,
            "diff_gt_0.5pct": diff_gt_05,
            "max_diff_pct": round(max_diff, 3),
        },
        "inverted_intervals": inverted,
        "baseline_reproduction": {
            "active_version": active.version_id,
            "stored": {k: stored.get(k) for k in ("total", "win_rate", "pass_rate", "dropout_rate")},
            "reproduced": {k: repro[k] for k in ("total", "win_rate", "pass_rate", "dropout_rate")},
            "abs_deltas_pp": deltas,
            "tolerance_pp": BASELINE_TOLERANCE,
            "ok": repro_ok,
        },
    }

    print(f"  원본 JSON {raw_items}건 → 로드 {len(raw)}건 → dedup {len(deduped)}건 (중복 {n_dup})")
    print(f"  연도별: {out['by_year_counts']}")
    print(f"  llr 결측(원본): {llr_missing}건 ({out['llr_missing_pct']}%) · 상위값 {llr_top[:3]}")
    print(f"  winner_rate 필드 괴리 >0.05%p: {diff_gt_005}건 (max {max_diff:.3f}%p) → 직접 계산 사용 타당")
    print(f"  역전 인터벌(낙찰가<하한선): {inverted}건")
    print(f"  기준선 재현 [{active.version_id}]: 저장 {stored.get('win_rate')}/{stored.get('dropout_rate')} vs 재현 "
          f"{repro['win_rate']}/{repro['dropout_rate']} (Δ {deltas}) → {'OK' if repro_ok else 'FAIL'}")

    if not repro_ok:
        print("  !! 기준선 재현 실패 — 사전 등록 부칙 3 에 따라 후속 실험 무효. 중단합니다.")
        sys.exit(1)
    return out


# ──────────────────────────────────────────────────────────────
# §C 실험 1 — 3정책 킬러윈도우 적중률
# ──────────────────────────────────────────────────────────────

def run_policies(records: list[ds.BidRecord], active_params: dict) -> dict:
    print("\n=== [policies] 3정책 킬러윈도우 적중률 ===")
    policies = {
        "standard_-2.5": lambda r: price_flat(r, -2.5),
        "active_v20260527": lambda r: price_params(r, active_params),
        "aggressive_-12": lambda r: price_flat(r, -12.0),
    }
    out: dict = {}
    for name, fn in policies.items():
        out[name] = slice_report(records, fn)
        o = out[name]["overall"]
        print(f"  {name:20s} win {o['win_rate']:6.2f}% (CI {o['win_ci95'][0]:.1f}~{o['win_ci95'][1]:.1f}) "
              f"dropout {o['dropout_rate']:6.2f}%  lost {o['lost_rate']:6.2f}%  (n={o['n']})")

    # sanity 3: active 자체 구현 == evaluate_params
    ev = evaluate_params(records, active_params)
    ours = out["active_v20260527"]["overall"]
    if abs(ev["win_rate"] - ours["win_rate"]) > 0.001:
        print(f"  !! sanity 실패: active 자체구현 {ours['win_rate']} != evaluate_params {ev['win_rate']}")
        sys.exit(1)
    print(f"  sanity(active==evaluate_params): OK ({ev['win_rate']}%)")
    return out


# ──────────────────────────────────────────────────────────────
# §D 실험 3 — 이론적 상한 (oracle)
# ──────────────────────────────────────────────────────────────

def oracle_max_hit(records: list[ds.BidRecord]) -> dict | None:
    """단일 고정 투찰률 t 의 사후 최대 적중 (인터벌 스위프, 정확해)."""
    intervals = []
    for r in records:
        iv = interval_of(r)
        if iv is not None:
            intervals.append(iv)
    n = len(records)
    if not intervals or n == 0:
        return None
    starts = sorted(iv[0] for iv in intervals)
    ends = sorted(iv[1] for iv in intervals)
    best_t, best_cnt = starts[0], 0
    cnt = i = j = 0
    while i < len(starts):
        if starts[i] <= ends[j]:
            cnt += 1
            if cnt > best_cnt:
                best_cnt, best_t = cnt, starts[i]
            i += 1
        else:
            cnt -= 1
            j += 1
    drop = sum(1 for (L, _u) in intervals if L > best_t)
    # 역전 인터벌 레코드: t >= L 이면 통과-패배, t < L 이면 탈락으로 집계
    for r in records:
        if interval_of(r) is None and r.basic_price > 0:
            if best_t < r.reserved_ratio * r.lower_limit_rate:
                drop += 1
    lo, hi = wilson_ci(best_cnt, n)
    return {
        "t_star": round(best_t, 4),
        "win_rate": round(best_cnt / n * 100.0, 3),
        "win_ci95": [round(lo, 3), round(hi, 3)],
        "dropout_rate": round(drop / n * 100.0, 3),
        "n": n,
    }


def run_oracle(records: list[ds.BidRecord]) -> dict:
    print("\n=== [oracle] 이론적 상한 + 과적합 정량화 ===")
    overall = oracle_max_hit(records)
    print(f"  전체 oracle: t*={overall['t_star']}% → win {overall['win_rate']}% "
          f"(CI {overall['win_ci95'][0]:.1f}~{overall['win_ci95'][1]:.1f}, dropout {overall['dropout_rate']}%)")

    by_seg: dict[str, dict] = {}
    seg_groups: dict[str, list] = {}
    for r in records:
        seg_groups.setdefault(f"{r.bid_method}/{r.bracket}", []).append(r)
    for seg, rs in sorted(seg_groups.items()):
        if len(rs) < MIN_SAMPLE:
            continue
        o = oracle_max_hit(rs)
        if o:
            by_seg[seg] = o

    by_year: dict[str, dict] = {}
    year_groups: dict[int, list] = {}
    for r in records:
        year_groups.setdefault(r.year, []).append(r)
    for y, rs in sorted(year_groups.items()):
        o = oracle_max_hit(rs)
        if o:
            by_year[str(y)] = o
            print(f"  {y} oracle: t*={o['t_star']}% → win {o['win_rate']}% (n={o['n']})")

    # walk-forward: 타 연도 t* 를 해당 연도에 적용 → in-sample oracle 대비 하락폭 = 과적합
    walk_forward = []
    years = sorted(year_groups)
    for y in years:
        train = [r for r in records if r.year != y]
        test = year_groups[y]
        if not train or not test:
            continue
        o_train = oracle_max_hit(train)
        o_test = by_year.get(str(y))
        if not o_train or not o_test:
            continue
        t = o_train["t_star"]
        applied = tally(test, lambda r, _t=t: math.floor(r.basic_price * _t / 100.0 / 10) * 10)
        walk_forward.append({
            "year": y,
            "n": len(test),
            "insample_oracle": o_test["win_rate"],
            "applied_t_star_from_other_years": t,
            "applied_win_rate": applied["win_rate"],
            "overfit_gap_pp": round(o_test["win_rate"] - applied["win_rate"], 3),
        })
        print(f"  walk-forward {y}: in-sample {o_test['win_rate']}% → 타연도 t* 적용 "
              f"{applied['win_rate']}% (gap {o_test['win_rate'] - applied['win_rate']:+.1f}%p)")

    # 입찰방법 × 연도 분해 — 전체 연도 변동이 레짐 변화인지 구성 착시인지 판별
    by_method_year: dict[str, dict[str, dict]] = {}
    method_counts: dict[str, int] = {}
    for r in records:
        method_counts[r.bid_method] = method_counts.get(r.bid_method, 0) + 1
    top_methods = [m for m, c in sorted(method_counts.items(), key=lambda kv: -kv[1])[:2]]
    for m in top_methods:
        by_method_year[m] = {}
        for y, rs in sorted(year_groups.items()):
            seg = [r for r in rs if r.bid_method == m]
            if len(seg) < MIN_SAMPLE:
                continue
            o = oracle_max_hit(seg)
            if o:
                by_method_year[m][str(y)] = o
        series = " / ".join(
            f"{y}:{o['win_rate']}%" for y, o in by_method_year[m].items()
        )
        print(f"  방법 고정 oracle [{m}]: {series}")

    # 연도별 oracle 분산 — "상한 자체가 흔들리는 정도"
    yr_rates = [o["win_rate"] for o in by_year.values()]
    mean = sum(yr_rates) / len(yr_rates) if yr_rates else 0.0
    std = math.sqrt(sum((v - mean) ** 2 for v in yr_rates) / len(yr_rates)) if yr_rates else 0.0

    # 모델 기반 사전 상한 곡선 (참고 — floor·winner 독립 가정 근사)
    model = ReservedRatioModel.fit(records)
    curve = []
    g = model.get_segment("__none__", "__none__")  # 전역 폴백
    for i in range(int(85.0 * 20), int(95.0 * 20) + 1):
        t = i / 20.0  # 0.05 간격
        p_pass = 1.0 - g.tail_probability(t / 87.745)
        p_below_winner = sum(
            1 for r in records
            if r.basic_price > 0 and r.winner_price / r.basic_price * 100.0 >= t
        ) / len(records)
        curve.append((t, p_pass * p_below_winner * 100.0))
    model_t, model_ceiling = max(curve, key=lambda c: c[1])
    print(f"  모델 상한(독립 가정 근사, 참고): t={model_t}% → {model_ceiling:.1f}%")

    return {
        "overall": overall,
        "by_segment": by_seg,
        "by_year": by_year,
        "by_method_year": by_method_year,
        "walk_forward": walk_forward,
        "year_oracle_mean": round(mean, 3),
        "year_oracle_std": round(std, 3),
        "model_prior_ceiling": {"t": model_t, "win_rate": round(model_ceiling, 3),
                                "note": "floor·winner 독립 가정 근사 — 참고용"},
    }


# ──────────────────────────────────────────────────────────────
# §E 실험 2 — 낙찰 최대화 프론티어
# ──────────────────────────────────────────────────────────────

def win_max_grid(seg_records: list[ds.BidRecord], adj_range, margin_range) -> list[dict]:
    """세그먼트 그리드 전 점의 (win, dropout) 캐시 — 균등 가중."""
    grid = []
    for adj in adj_range:
        for margin in margin_range:
            sim = simulate_params(seg_records, adj, margin)
            grid.append({
                "adj": adj, "margin": margin,
                "win": sim["win_rate"],
                "drop": sim["dropout_rate_uw"],
            })
    return grid


def run_frontier(
    train: list[ds.BidRecord],
    holdout: list[ds.BidRecord],
    active_params: dict,
    wide: bool = False,
) -> dict:
    adj_range = WIDE_ADJ if wide else GRID_ADJ
    margin_range = WIDE_MARGIN if wide else GRID_MARGIN
    label = "wide" if wide else "standard"
    print(f"\n=== [frontier] 낙찰 최대화 프론티어 (grid={label}, fit 2021~2024 → holdout 2025) ===")

    # 세그먼트별 그리드 1회 계산 (캡별 재계산 없음)
    seg_grids: dict[tuple[str, str], list[dict]] = {}
    for method, bracket in ds.iter_segments(train):
        seg_records = ds.filter_segment(train, method, bracket)
        if len(seg_records) < MIN_SAMPLE:
            continue  # 희소 세그먼트는 active 상속
        seg_grids[(method, bracket)] = win_max_grid(seg_records, adj_range, margin_range)

    holdout_oracle = oracle_max_hit(holdout) if holdout else None

    points = []
    prev_train_win = -1.0
    for cap in DROPOUT_CAPS:
        # active 파라미터에서 출발 (희소 세그먼트 상속) + 낙찰 최대화 점으로 대체
        params = {m: {b: list(v) for b, v in br.items()} for m, br in active_params.items()}
        for (method, bracket), grid in seg_grids.items():
            cands = [g for g in grid if cap is None or g["drop"] <= cap]
            if not cands:  # 캡 불만족 세그먼트 — 최소 위험점으로
                cands = [min(grid, key=lambda g: g["drop"])]
            best = max(cands, key=lambda g: (g["win"], -g["drop"]))
            params.setdefault(method, {})[bracket] = [best["adj"], best["margin"]]

        m_train = evaluate_params(train, params)
        m_hold = evaluate_params(holdout, params) if holdout else {}
        # holdout win 의 Wilson CI (게이트 부칙 2 — CI 하한 판정용)
        if holdout:
            k = round(m_hold["win_rate"] / 100.0 * len(holdout))
            ci = wilson_ci(int(k), len(holdout))
        else:
            ci = (0.0, 0.0)
        pt = {
            "dropout_cap_pp": cap,
            "train": {k: m_train[k] for k in ("win_rate", "pass_rate", "dropout_rate")},
            "holdout": (
                {k: m_hold[k] for k in ("win_rate", "pass_rate", "dropout_rate")} if holdout else {}
            ),
            "holdout_win_ci95": [round(ci[0], 3), round(ci[1], 3)],
            "holdout_oracle_attainment_pct": (
                round(m_hold["win_rate"] / holdout_oracle["win_rate"] * 100.0, 1)
                if holdout and holdout_oracle and holdout_oracle["win_rate"] > 0 else None
            ),
            "params": params,
        }
        points.append(pt)
        cap_s = f"{cap:.0f}%" if cap is not None else "무제약"
        print(f"  cap {cap_s:>5s}: train win {m_train['win_rate']:6.2f}% / drop {m_train['dropout_rate']:5.2f}%"
              + (f"  | holdout win {m_hold['win_rate']:6.2f}% (CI {ci[0]:.1f}~{ci[1]:.1f}) "
                 f"/ drop {m_hold['dropout_rate']:5.2f}%" if holdout else ""))

        # sanity 2: train 단조성 (캡 완화 → win 비감소)
        if m_train["win_rate"] < prev_train_win - 0.001:
            print(f"  !! sanity 실패: 프론티어 단조성 위반 (cap {cap})")
            sys.exit(1)
        prev_train_win = max(prev_train_win, m_train["win_rate"])

    return {
        "grid": label,
        "holdout_years": list(HOLDOUT_YEARS),
        "holdout_oracle": holdout_oracle,
        "points": [
            {k: v for k, v in p.items() if k != "params"} for p in points
        ],
        "best_params_at_cap10": next(
            (p["params"] for p in points if p["dropout_cap_pp"] == 10.0), None
        ),
    }


# ──────────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="낙찰 도달 성능 벤치마크")
    ap.add_argument("--exp", choices=["audit", "policies", "oracle", "frontier", "all"],
                    default="all")
    ap.add_argument("--quick", action="store_true", help="1/10 표본 스모크")
    ap.add_argument("--wide", action="store_true", help="확장 그리드 (frontier)")
    ap.add_argument("--json-out", default=str(RESULTS_PATH))
    args = ap.parse_args()

    print(f"낙찰 도달 벤치마크 — exp={args.exp} quick={args.quick} wide={args.wide}")
    raw, deduped, n_dup = load_all()
    store = get_default_store()
    active_params = store.load_active().params

    records = quick_sample(deduped) if args.quick else deduped
    if args.quick:
        print(f"  (--quick: {len(deduped)} → {len(records)}건 등간 표본)")

    results: dict = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "quick": args.quick,
        "n_records": len(records),
    }

    run_all = args.exp == "all"
    if run_all or args.exp == "audit":
        results["audit"] = run_audit(raw, deduped, n_dup)
    if run_all or args.exp == "policies":
        results["policies"] = run_policies(records, active_params)
    if run_all or args.exp == "oracle":
        results["oracle"] = run_oracle(records)
    if run_all or args.exp == "frontier":
        train, holdout = ds.split_by_year(records, HOLDOUT_YEARS)
        results["frontier"] = run_frontier(train, holdout, active_params, wide=args.wide)

    # sanity 1: oracle ≥ 모든 정책/프론티어 win (동일 레코드셋 기준)
    if "oracle" in results and "policies" in results:
        ceiling = results["oracle"]["overall"]["win_rate"]
        for name, rep in results["policies"].items():
            if rep["overall"]["win_rate"] > ceiling + 0.001:
                print(f"!! sanity 실패: {name} win {rep['overall']['win_rate']} > oracle {ceiling}")
                sys.exit(1)
        print(f"\nsanity(oracle 상한 {ceiling}% ≥ 모든 정책): OK")

    # 부분 실행(--exp 단일) 시 기존 결과의 다른 섹션 보존 (병합 저장)
    out_path = Path(args.json_out)
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            if existing.get("quick") == args.quick:
                merged = {**existing, **results}
                results = merged
        except (json.JSONDecodeError, OSError):
            pass
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
