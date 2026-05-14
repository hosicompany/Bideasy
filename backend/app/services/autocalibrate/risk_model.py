"""
하한선 탈락 위험 명시 모델링 (특허 신규성 핵심)
================================================
종래: "통과율 >= 임계값" 하드 제약 — 임의 컷오프, 건별 위험 구조 없음.

본 모듈: 사정비율 r = 예정가격/기초금액 을 세그먼트별 **확률분포**로 추정하고,
파라미터로부터 임계비율 r* 를 **해석적으로 유도**하여 각 입찰건의
탈락 확률 P(r > r*) 를 산출한다.

수식:
  우리 투찰가  bid   = basic × (1+adj/100) × (lower_rate+margin)/100
  실제 하한선  limit = reserved × lower_rate/100,   reserved = basic × r
  탈락 ⇔ bid < limit ⇔ r > r*(θ)
  여기서  r*(θ) = (1+adj/100) × (lower_rate+margin) / lower_rate
  따라서  P(dropout | θ, s) = P(r > r*(θ) | s)  = 세그먼트 r-분포의 상위 꼬리 확률

희소 세그먼트는 계층적 폴백(세그먼트 → 입찰방법 → 전역) + 베이지안 shrinkage
로 부모 분포 쪽으로 보정한다.

순수 함수 + numpy 만 사용 (sklearn 등 무거운 의존성 없음).
4번 확장 시 dropout_probability 인터페이스를 ML 모델로 교체 가능.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.services.autocalibrate.dataset import BidRecord

# 세그먼트가 자체 분포를 가질 최소 표본 수 (미만이면 부모로 폴백)
MIN_SEGMENT_SAMPLE = 30
# 베이지안 shrinkage 강도 — μ_shrunk = w·μ_seg + (1-w)·μ_parent, w = n/(n+k)
SHRINKAGE_K = 25.0
# σ 하한 (분산 0 방지)
MIN_SIGMA = 1e-4


@dataclass
class SegmentRiskParams:
    """한 세그먼트의 사정비율 r 분포 파라미터."""

    mu: float                 # 가중 평균
    sigma: float              # 가중 표준편차
    n_effective: float        # 유효 표본 수 (가중합)
    n_raw: int                # 원시 표본 수
    source: str               # "own" | "shrunk:method" | "shrunk:global"
    quantiles: dict = field(default_factory=dict)  # {0.05: ..., 0.5: ..., 0.95: ...}

    def tail_probability(self, r_star: float) -> float:
        """P(r > r_star) — 정규 근사 상위 꼬리 확률."""
        if self.sigma <= MIN_SIGMA:
            return 1.0 if r_star < self.mu else 0.0
        z = (r_star - self.mu) / self.sigma
        # 정규 생존함수 = 0.5 * erfc(z / sqrt(2))
        return 0.5 * math.erfc(z / math.sqrt(2.0))


def _weighted_mean_std(values: list[float], weights: list[float]) -> tuple[float, float, float]:
    """가중 평균·표준편차·유효표본수."""
    w_sum = sum(weights)
    if w_sum <= 0:
        return 0.0, 0.0, 0.0
    mu = sum(v * w for v, w in zip(values, weights)) / w_sum
    var = sum(w * (v - mu) ** 2 for v, w in zip(values, weights)) / w_sum
    return mu, math.sqrt(max(var, 0.0)), w_sum


def _weighted_quantiles(
    values: list[float], weights: list[float], qs: tuple[float, ...]
) -> dict:
    """가중 분위수 (보간)."""
    if not values:
        return {q: 0.0 for q in qs}
    pairs = sorted(zip(values, weights))
    total = sum(w for _, w in pairs)
    out = {}
    for q in qs:
        target = q * total
        cum = 0.0
        result = pairs[-1][0]
        for v, w in pairs:
            cum += w
            if cum >= target:
                result = v
                break
        out[q] = result
    return out


class ReservedRatioModel:
    """세그먼트별 사정비율 r 분포 모델 (계층 폴백 + shrinkage)."""

    def __init__(self):
        self._segments: dict[tuple[str, str], SegmentRiskParams] = {}
        self._by_method: dict[str, SegmentRiskParams] = {}
        self._global: SegmentRiskParams | None = None

    @classmethod
    def fit(
        cls,
        records: list[BidRecord],
        year_weights: dict[int, float] | None = None,
    ) -> "ReservedRatioModel":
        """과거 레코드로 세그먼트별 r 분포 적합."""
        model = cls()
        year_weights = year_weights or {}

        def w_of(r: BidRecord) -> float:
            return year_weights.get(r.year, 1.0)

        # 전역 분포
        g_vals = [r.reserved_ratio for r in records if r.reserved_ratio > 0]
        g_wts = [w_of(r) for r in records if r.reserved_ratio > 0]
        if g_vals:
            mu, sigma, neff = _weighted_mean_std(g_vals, g_wts)
            model._global = SegmentRiskParams(
                mu=mu,
                sigma=max(sigma, MIN_SIGMA),
                n_effective=neff,
                n_raw=len(g_vals),
                source="global",
                quantiles=_weighted_quantiles(g_vals, g_wts, (0.05, 0.25, 0.5, 0.75, 0.95)),
            )

        # 입찰방법별 분포
        methods: dict[str, list[BidRecord]] = {}
        for r in records:
            methods.setdefault(r.bid_method, []).append(r)
        for method, recs in methods.items():
            vals = [r.reserved_ratio for r in recs if r.reserved_ratio > 0]
            wts = [w_of(r) for r in recs if r.reserved_ratio > 0]
            if vals:
                mu, sigma, neff = _weighted_mean_std(vals, wts)
                model._by_method[method] = SegmentRiskParams(
                    mu=mu,
                    sigma=max(sigma, MIN_SIGMA),
                    n_effective=neff,
                    n_raw=len(vals),
                    source="method",
                    quantiles=_weighted_quantiles(vals, wts, (0.05, 0.5, 0.95)),
                )

        # 세그먼트별 분포 (입찰방법 × 금액대) + shrinkage
        segments: dict[tuple[str, str], list[BidRecord]] = {}
        for r in records:
            segments.setdefault(r.segment, []).append(r)
        for seg, recs in segments.items():
            method, bracket = seg
            vals = [r.reserved_ratio for r in recs if r.reserved_ratio > 0]
            wts = [w_of(r) for r in recs if r.reserved_ratio > 0]
            if not vals:
                continue
            mu, sigma, neff = _weighted_mean_std(vals, wts)
            n_raw = len(vals)

            parent = model._by_method.get(method) or model._global
            if n_raw >= MIN_SEGMENT_SAMPLE or parent is None:
                # 충분한 표본 — 자체 분포
                model._segments[seg] = SegmentRiskParams(
                    mu=mu,
                    sigma=max(sigma, MIN_SIGMA),
                    n_effective=neff,
                    n_raw=n_raw,
                    source="own",
                    quantiles=_weighted_quantiles(vals, wts, (0.05, 0.5, 0.95)),
                )
            else:
                # 희소 세그먼트 — 베이지안 shrinkage (부모 쪽으로 당김)
                w = n_raw / (n_raw + SHRINKAGE_K)
                mu_s = w * mu + (1 - w) * parent.mu
                sigma_s = w * max(sigma, MIN_SIGMA) + (1 - w) * parent.sigma
                model._segments[seg] = SegmentRiskParams(
                    mu=mu_s,
                    sigma=max(sigma_s, MIN_SIGMA),
                    n_effective=neff,
                    n_raw=n_raw,
                    source=f"shrunk:{parent.source}",
                    quantiles=parent.quantiles,
                )
        return model

    def get_segment(self, method: str, bracket: str) -> SegmentRiskParams:
        """세그먼트 분포 조회 — 없으면 계층 폴백 (method → global)."""
        seg = self._segments.get((method, bracket))
        if seg is not None:
            return seg
        by_method = self._by_method.get(method)
        if by_method is not None:
            return by_method
        if self._global is not None:
            return self._global
        # 극단 폴백 — 데이터 전무
        return SegmentRiskParams(mu=0.95, sigma=0.03, n_effective=0, n_raw=0, source="fallback")

    # ── 핵심: 탈락 확률 계산 ────────────────────────────────
    @staticmethod
    def critical_ratio(adjustment: float, margin: float, lower_rate: float) -> float:
        """임계비율 r*(θ) = (1+adj/100) × (lower_rate+margin) / lower_rate.

        r 이 이 값을 초과하면 우리 투찰가가 실제 하한선 미만 → 탈락.
        """
        if lower_rate <= 0:
            return float("inf")
        return (1 + adjustment / 100.0) * (lower_rate + margin) / lower_rate

    def dropout_probability(
        self,
        adjustment: float,
        margin: float,
        method: str,
        bracket: str,
        lower_rate: float = 87.745,
    ) -> float:
        """주어진 파라미터로 투찰 시 해당 세그먼트의 탈락 확률 P(r > r*)."""
        r_star = self.critical_ratio(adjustment, margin, lower_rate)
        seg = self.get_segment(method, bracket)
        return seg.tail_probability(r_star)

    def expected_dropout_rate(
        self,
        params: dict,
        records: list[BidRecord],
    ) -> float:
        """전체 레코드에 대한 기대 탈락률 (파라미터셋 평가용)."""
        if not records:
            return 0.0
        total = 0.0
        for r in records:
            method_params = params.get(r.bid_method, params.get("DEFAULT", {}))
            p = method_params.get(r.bracket)
            if p is None:
                p = params.get("DEFAULT", {}).get(r.bracket, [-0.3, 1.0])
            adj, margin = float(p[0]), float(p[1])
            total += self.dropout_probability(
                adj, margin, r.bid_method, r.bracket, r.lower_limit_rate
            )
        return total / len(records)

    def calibration_error(self, records: list[BidRecord], params: dict) -> float:
        """예측 탈락확률 평균 vs 실측 탈락률의 절대 괴리 (모델 자기진단).

        특허 신규성 5 — 위험 자기진단 지표.
        """
        if not records:
            return 0.0
        predicted = self.expected_dropout_rate(params, records)
        # 실측: 각 레코드에 파라미터 적용 → 실제 탈락 여부
        actual_dropouts = 0
        for r in records:
            method_params = params.get(r.bid_method, params.get("DEFAULT", {}))
            p = method_params.get(r.bracket)
            if p is None:
                p = params.get("DEFAULT", {}).get(r.bracket, [-0.3, 1.0])
            adj, margin = float(p[0]), float(p[1])
            bid = r.basic_price * (1 + adj / 100.0) * (r.lower_limit_rate + margin) / 100.0
            limit = r.reserved_price * r.lower_limit_rate / 100.0
            if bid < limit:
                actual_dropouts += 1
        actual = actual_dropouts / len(records)
        return abs(predicted - actual)

    def summary(self) -> dict:
        """모델 요약 (디버깅/리포트용)."""
        return {
            "n_segments": len(self._segments),
            "n_methods": len(self._by_method),
            "global": (
                {"mu": round(self._global.mu, 5), "sigma": round(self._global.sigma, 5)}
                if self._global
                else None
            ),
            "segments": {
                f"{m}/{b}": {
                    "mu": round(p.mu, 5),
                    "sigma": round(p.sigma, 5),
                    "n_raw": p.n_raw,
                    "source": p.source,
                }
                for (m, b), p in sorted(self._segments.items())
            },
        }
