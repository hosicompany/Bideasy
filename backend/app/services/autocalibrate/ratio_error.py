"""사정률 예측 오차 후보의 시간 안전한 검증.

모의투찰 ``active`` arm 의 기존 기준선은 등록 당시 adjustment 를
``1 + adjustment / 100`` 으로 바꾼 값이다. 이 모듈은 그 의사결정값과
autocalibrate 위험모델의 사정비율 중앙값을 분리해 비교한다.

⚠️ **walk-forward 규칙은 후보에만 적용된다.** 후보는 매 fold 를
``train.year < holdout.year`` 로 다시 적합하지만, 기준선인 ``active`` 파라미터는
2021~2025 전체로 적합된 저장본을 그대로 쓴다 — 즉 2022~2025 holdout 에서
**기준선은 미래를 본다**. 방향은 안전하다(기준선에 유리한데도 후보가 이기면
결론은 더 견고해진다). 대신 **개선폭은 하한**이므로 이 모듈의 delta 를 성과로
인용하지 말 것. 같은 조건에서 fold 별로 재적합한 기준선과의 대조는
``scripts/analyze_ratio_error.py --exp walkforward`` 가 담당한다.

결과는 그림자 후보 제안일 뿐이다. active 전략 저장소는 **읽기만** 하고
(호출부가 기준선 파라미터를 넘긴다) 쓰지 않는다.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass

from app.services.autocalibrate.dataset import BidRecord
from app.services.autocalibrate.optimizer import adaptive_year_weights
from app.services.autocalibrate.risk_model import ReservedRatioModel
from app.services.bid_data_quality import BASE_RATIO_MAX, BASE_RATIO_MIN

ORGANIZATION_SHRINKAGE_K = 25.0
MAX_YEARLY_MAE_REGRESSION = 0.0001
# 후보 간 MAE 차이가 이 안이면 구분되지 않은 것으로 보고 단순한 쪽을 고른다.
# 연도별 회귀 허용치와 같은 스케일을 쓴다 — 한 해치 흔들림보다 작은 차이를
# 우열로 읽지 않겠다는 뜻이다.
TIE_MARGIN = MAX_YEARLY_MAE_REGRESSION


def _active_prediction(record: BidRecord, params: dict) -> float:
    """현재 active 파라미터가 모의투찰에 기록하는 사정비율 예측값."""
    method_params = params.get(record.bid_method, params.get("DEFAULT", {}))
    pair = method_params.get(record.bracket)
    if pair is None:
        pair = params.get("DEFAULT", {}).get(record.bracket, [-0.3, 1.0])
    return 1.0 + float(pair[0]) / 100.0


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - index) + ordered[upper] * (index - lower)


def error_metrics(errors: list[float]) -> dict:
    """ratio 단위 절대오차의 MAE·중앙값·p90."""
    if not errors:
        return {"n": 0, "mae": None, "median": None, "p90": None}
    return {
        "n": len(errors),
        "mae": round(statistics.fmean(errors), 6),
        "median": round(statistics.median(errors), 6),
        "p90": round(float(_percentile(errors, 0.9)), 6),
    }


def _valid_records(records: list[BidRecord]) -> tuple[list[BidRecord], int]:
    valid = [
        record
        for record in records
        if BASE_RATIO_MIN <= record.reserved_ratio <= BASE_RATIO_MAX
    ]
    return valid, len(records) - len(valid)


@dataclass(frozen=True)
class OrganizationCell:
    median: float
    n: int


class RatioPredictionCandidates:
    """세그먼트 중앙값과 기관 부분풀링 후보를 같은 학습창에서 적합."""

    def __init__(
        self,
        segment_model: ReservedRatioModel,
        organization_cells: dict[tuple[str, str, str], OrganizationCell],
    ):
        self.segment_model = segment_model
        self.organization_cells = organization_cells

    @classmethod
    def fit(cls, records: list[BidRecord]) -> "RatioPredictionCandidates":
        valid, _ = _valid_records(records)
        weights = adaptive_year_weights(valid)
        segment_model = ReservedRatioModel.fit(valid, weights)

        grouped: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        for record in valid:
            organization = (record.org or "").strip()
            if organization:
                key = (record.bid_method, record.bracket, organization)
                grouped[key].append(record.reserved_ratio)
        cells = {
            key: OrganizationCell(median=statistics.median(values), n=len(values))
            for key, values in grouped.items()
        }
        return cls(segment_model, cells)

    def predict_segment(self, record: BidRecord) -> float:
        return self.segment_model.predict_reserved_ratio(
            record.bid_method, record.bracket
        )

    def predict_organization(self, record: BidRecord) -> float:
        """기관 셀은 부모(방법×금액대) 중앙값으로 부분풀링한다."""
        parent = self.predict_segment(record)
        organization = (record.org or "").strip()
        if not organization:
            return parent
        cell = self.organization_cells.get(
            (record.bid_method, record.bracket, organization)
        )
        if cell is None:
            return parent
        weight = cell.n / (cell.n + ORGANIZATION_SHRINKAGE_K)
        return weight * cell.median + (1.0 - weight) * parent


def _prediction_errors(
    records: list[BidRecord],
    baseline_params: dict,
    candidates: RatioPredictionCandidates,
) -> dict[str, list[float]]:
    errors = {
        "active_adjustment": [],
        "segment_median": [],
        "organization_shrunk": [],
    }
    for record in records:
        actual = record.reserved_ratio
        errors["active_adjustment"].append(
            abs(actual - _active_prediction(record, baseline_params))
        )
        errors["segment_median"].append(
            abs(actual - candidates.predict_segment(record))
        )
        errors["organization_shrunk"].append(
            abs(actual - candidates.predict_organization(record))
        )
    return errors


def _fold_result(
    train: list[BidRecord],
    holdout: list[BidRecord],
    baseline_params: dict,
) -> tuple[dict, dict[str, list[float]]]:
    candidates = RatioPredictionCandidates.fit(train)
    train_errors = _prediction_errors(train, baseline_params, candidates)
    holdout_errors = _prediction_errors(holdout, baseline_params, candidates)

    metrics = {name: error_metrics(values) for name, values in holdout_errors.items()}
    baseline_mae = metrics["active_adjustment"]["mae"]
    for name in ("segment_median", "organization_shrunk"):
        metrics[name]["delta_vs_active"] = round(
            metrics[name]["mae"] - baseline_mae, 6
        )
        metrics[name]["overfit_gap"] = round(
            metrics[name]["mae"] - error_metrics(train_errors[name])["mae"], 6
        )
    return metrics, holdout_errors


def walk_forward_validate(
    records: list[BidRecord],
    baseline_params: dict,
    *,
    min_train_years: int = 1,
) -> dict:
    """과거 연도만 학습해 다음 연도를 평가하는 expanding walk-forward.

    기관 부분풀링은 같은 fold에서 비교하되, 기관 효과가 세그먼트 중앙값보다
    낫다는 증거가 없으면 더 단순한 후보를 선택한다. A값은 정적 2021~2025
    원장에 사전시점 스냅샷이 없어 후보 특성으로 사용하지 않는다.
    """
    valid, excluded = _valid_records(records)
    years = sorted({record.year for record in valid})
    folds: list[dict] = []
    pooled: dict[str, list[float]] = defaultdict(list)

    for holdout_year in years:
        train_years = [year for year in years if year < holdout_year]
        if len(train_years) < min_train_years:
            continue
        train = [record for record in valid if record.year < holdout_year]
        holdout = [record for record in valid if record.year == holdout_year]
        if not train or not holdout:
            continue
        metrics, errors = _fold_result(train, holdout, baseline_params)
        for name, values in errors.items():
            pooled[name].extend(values)
        folds.append(
            {
                "holdout_year": holdout_year,
                "train_years": train_years,
                "train_n": len(train),
                "holdout_n": len(holdout),
                **metrics,
            }
        )

    pooled_metrics = {name: error_metrics(values) for name, values in pooled.items()}
    baseline_mae = pooled_metrics.get("active_adjustment", {}).get("mae")
    candidate_names = ("segment_median", "organization_shrunk")
    selection: dict[str, dict] = {}
    for name in candidate_names:
        mae = pooled_metrics.get(name, {}).get("mae")
        deltas = [fold[name]["delta_vs_active"] for fold in folds]
        max_regression = max(deltas) if deltas else None
        passed = bool(
            mae is not None
            and baseline_mae is not None
            and mae < baseline_mae
            and max_regression is not None
            and max_regression <= MAX_YEARLY_MAE_REGRESSION
        )
        selection[name] = {
            "pooled_delta_vs_active": (
                round(mae - baseline_mae, 6)
                if mae is not None and baseline_mae is not None
                else None
            ),
            "max_yearly_regression": max_regression,
            "selection_rule_passed": passed,
        }

    eligible = [
        name for name in candidate_names if selection[name]["selection_rule_passed"]
    ]
    # ⚠️ 단순성 우선 — `candidate_names` 는 복잡도 오름차순이고, MAE 가
    # `TIE_MARGIN` 안에서 갈리면 **더 단순한 후보**를 고른다.
    #
    # 순수 MAE 최소로 고르면 두 후보가 구분되지 않을 때 복잡한 쪽이 이긴다.
    # 실측 차이는 0.00001 수준(세그먼트 0.005876 vs 기관 0.005886)이라
    # 연도 하나만 바뀌어도 순위가 뒤집히는데, 그 승부에 기관 차원을 얹으면
    # 얻는 것 없이 적합할 모수만 늘어난다. 동점이면 덜 쪼갠 쪽이 이긴다.
    best_mae = min(
        (pooled_metrics[name]["mae"] for name in eligible), default=None
    )
    selected = next(
        (
            name
            for name in candidate_names
            if name in eligible and pooled_metrics[name]["mae"] <= best_mae + TIE_MARGIN
        ),
        None,
    )
    return {
        "sample": {
            "raw": len(records),
            "included": len(valid),
            "excluded_basis_inconsistent": excluded,
            "years": years,
        },
        "scheme": "expanding_year",
        "folds": folds,
        "pooled": pooled_metrics,
        "selection": selection,
        "selected_shadow_candidate": selected,
        "promotion_allowed": False,
        # 기준선은 fold 별 재적합이 아니다(모듈 docstring). 이 JSON 만 보고
        # delta 를 성과로 읽는 것을 막기 위해 페이로드에 사실을 박아 둔다.
        "baseline_is_walk_forward": False,
        "notes": [
            "후보의 holdout 예측은 해당 연도보다 앞선 데이터만 사용한다.",
            "기준선(active)은 2021~2025 로 적합된 저장본이라 walk-forward 가 "
            "아니다 — 기준선에 유리하므로 delta 는 개선폭의 하한이다. "
            "동일 조건 재적합 대조는 scripts/analyze_ratio_error.py 참조.",
            "A값은 과거 사전시점 스냅샷이 없어 후보 특성에서 제외했다.",
            "결과는 제안·검증 전용이며 active 전략을 변경하지 않는다.",
        ],
    }
