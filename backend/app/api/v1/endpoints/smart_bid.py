"""
스마트 투찰 API
- 참여수 예측 (블루오션 탐지)
- 참여수 적응형 최적 투찰가 추천
- 유형별 낙찰률 예측
- 기관별 낙찰률 통계
- 발주처 인사이트 (Historical DB)
- 투찰 역검증 ("왜 떨어졌을까?")
"""

import logging
import os
import sqlite3 as _sqlite
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.core.security import require_tier
from app.db.session import get_db
from app.schemas.algorithm_evidence import (
    RecommendationDecisionContract,
    RecommendationPolicy,
)
from app.services.algorithm_evidence import canonical_hash, record_recommendation
from app.services.bid_route import (
    BidRoute,
    classify_bid_route,
    normalize_bid_method,
    supports_smart_bid,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ML 스택(numpy/joblib) 부재·모델 미탑재 시 발생하는 예외 — 500 대신 정직한 503 으로.
# (2026-07-18: 죽은 ML 서비스가 500 + 내부 에러 문자열을 노출하던 문제 수습)

_UNAVAILABLE_ERRORS = (
    ImportError,
    ModuleNotFoundError,
    FileNotFoundError,
    _sqlite.OperationalError,
    RuntimeError,
)
_UNAVAILABLE_MSG = "이 기능은 현재 준비 중이에요. 잠시 후 다시 시도해 주세요."
_GENERIC_ERROR_MSG = "요청 처리 중 오류가 발생했어요."


# ============================================================
# Request/Response Models
# ============================================================

class CompetitionPredictRequest(BaseModel):
    bid_type: str = Field(..., description="입찰 유형 (construction, goods, service)")
    estimated_amount: float = Field(..., description="추정 금액")
    agency_name: str = Field("", description="발주기관명")
    bid_date: Optional[str] = Field(None, description="입찰일 (YYYY-MM-DD)")


class SmartBidRequest(BaseModel):
    base_amount: Optional[float] = Field(None, gt=0, description="확인된 기초금액")
    basis_status: Optional[str] = Field(None, description="confirmed | unconfirmed")
    bid_type: Optional[str] = Field(None, description="입찰 유형")
    bid_no: Optional[str] = Field(None, description="공고번호 (evidence 연결용)")
    bid_method: Optional[str] = Field(None, description="낙찰자 결정방법")
    contract_method: Optional[str] = Field(None, description="계약방법 (route 분류 보조)")
    a_value: float = Field(0, ge=0, description="A값 (시설공사)")
    a_value_status: Optional[str] = Field(
        None,
        description="confirmed | not_applicable | unknown",
    )
    lower_limit_rate: Optional[float] = Field(
        None,
        gt=0,
        le=100,
        description="공고가 명시한 낙찰하한율(%)",
    )
    prdprc_range_bgn: Optional[float] = Field(
        None,
        ge=-20,
        le=20,
        description="공고가 명시한 예정가격 범위 시작율(%)",
    )
    prdprc_range_end: Optional[float] = Field(
        None,
        ge=-20,
        le=20,
        description="공고가 명시한 예정가격 범위 종료율(%)",
    )
    estimated_amount: Optional[float] = Field(None, description="추정가격")
    agency_name: str = Field("", description="발주기관명")
    agency_type: str = Field("national", description="발주기관 유형 (national, local, public_corp)")
    bid_date: Optional[date] = Field(None, description="입찰일 (YYYY-MM-DD)")
    margin_pct: Optional[float] = Field(None, description="수동 마진 (None이면 자동)")

    @model_validator(mode="after")
    def validate_formula_inputs(self) -> "SmartBidRequest":
        if self.base_amount is not None and self.a_value >= self.base_amount:
            raise ValueError("A값은 확정 기초금액 미만이어야 합니다")
        normalized_a_status = (self.a_value_status or "").lower()
        if normalized_a_status == "not_applicable" and self.a_value != 0:
            raise ValueError("A값 비대상 공고에는 양수 A값을 사용할 수 없습니다")
        if normalized_a_status == "confirmed" and self.a_value <= 0:
            raise ValueError("확정 A값은 0보다 커야 합니다")
        if (self.prdprc_range_bgn is None) != (self.prdprc_range_end is None):
            raise ValueError("예정가격 범위 시작·종료값을 함께 보내야 합니다")
        if (
            self.prdprc_range_bgn is not None
            and self.prdprc_range_end is not None
            and self.prdprc_range_bgn > self.prdprc_range_end
        ):
            raise ValueError("예정가격 범위 시작값은 종료값보다 클 수 없습니다")
        return self


class BidRatePredictRequest(BaseModel):
    bid_type: str = Field(..., description="입찰 유형")
    estimated_amount: float = Field(..., description="추정 금액")
    expected_participants: int = Field(10, description="예상 참여업체수")
    agency_name: str = Field("", description="발주기관명")
    bid_date: Optional[str] = Field(None, description="입찰일")


class BidVerifyRequest(BaseModel):
    bid_no: str = Field(..., description="공고번호")
    my_bid_price: float = Field(..., description="내 투찰가")
    basic_price: float = Field(..., description="기초금액")
    organization: str = Field("", description="발주기관명")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _bid_date_text(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _planned_price_range(req: SmartBidRequest) -> dict[str, Any]:
    """공고에 명시된 복수예비가 범위만 노출한다.

    공고 메타데이터가 없으면 범용 ``±3%``를 대입하지 않고
    ``null + reason``으로 응답한다.
    """
    if (
        req.base_amount is None
        or req.prdprc_range_bgn is None
        or req.prdprc_range_end is None
    ):
        return {
            "low": None,
            "high": None,
            "source": None,
            "unavailable_reason": "공고에서 예정가격 범위를 확인하지 못했어요.",
        }

    from app.services.calculator import CalculatorService

    return {
        "low": CalculatorService.calculate_price_at_rate(
            req.base_amount,
            100 + req.prdprc_range_bgn,
        ),
        "high": CalculatorService.calculate_price_at_rate(
            req.base_amount,
            100 + req.prdprc_range_end,
        ),
        "source": "notice_public_range",
        "unavailable_reason": None,
    }


def _a_adjusted_price(reference_price: float, rate_pct: float, a_value: float) -> int:
    """A값 공식을 적용한 가격을 전 채널 규칙대로 10원 절사한다."""
    from app.services.calculator import CalculatorService

    return CalculatorService.calculate_price_at_rate(
        reference_price,
        rate_pct,
        a_value,
    )


def _calculator_bid_rate_pct(
    *,
    basic_price: float,
    recommended_price: float,
    a_value: float,
) -> float:
    """Flutter A값 계산기가 추천가를 재현할 수 있는 적용률을 역산한다.

    10원 절사 구간의 정가운데(+5원)를 목표로 삼아 Python→JSON→Dart
    부동소수점 변환 오차가 절사 경계 아래로 밀어내지 못하게 한다.
    """
    variable_basis = basic_price - a_value
    if variable_basis <= 0:
        raise ValueError("A값 적용 후 변동 기초금액은 0보다 커야 합니다")
    return ((recommended_price + 5 - a_value) / variable_basis) * 100


def _unverified_probabilities() -> dict[str, Any]:
    """확률 calibration 전에는 숫자를 꾸며내지 않고 null + 이유를 반환한다."""
    return {
        "below_lower_limit": None,
        "price_rank_one": None,
        "final_award": None,
        "unavailable_reason": "확률 보정 및 route별 승격 기준을 아직 통과하지 않았어요.",
    }


def _request_evidence(
    req: SmartBidRequest,
    method: str | None,
    *,
    basis: str | None,
) -> dict[str, Any]:
    return {
        "basis": basis,
        "validation_status": "probability_not_calibrated",
        "bid_no": req.bid_no,
        "bid_method": method,
        "basis_status": req.basis_status,
        "lower_limit_source": (
            "notice"
            if req.lower_limit_rate is not None
            else "versioned_rule_table"
            if req.bid_date is not None
            else None
        ),
        "planned_price_range_source": (
            "notice_public_range"
            if req.prdprc_range_bgn is not None
            else None
        ),
        "sample_size": None,
        "latest_observation_at": None,
    }


def _abstain_data(
    req: SmartBidRequest,
    *,
    route: BidRoute,
    code: str,
    reason: str,
) -> dict[str, Any]:
    """기존 JSON 키는 유지하되 가격을 0으로 위장하지 않는 명시적 기권 응답."""
    method = normalize_bid_method(req.bid_method)
    return {
        "recommendation_id": str(uuid4()),
        "as_of": _iso_utc(_now_utc()),
        "route": route.value,
        "strategy_version": None,
        "decision_status": "abstained",
        "abstain_code": code,
        "abstain_reason": reason,
        "evidence": _request_evidence(req, method, basis=None),
        "probabilities": _unverified_probabilities(),
        # 아래 키는 구버전 클라이언트 파싱 호환용이다. null은 추천가가 없다는 뜻이다.
        "optimal_bid": None,
        "lower_limit": None,
        "lower_limit_pct": "",
        "applied_margin_pct": None,
        "effective_rate": None,
        "expected_planned_price": {
            "mean": None,
            "mean_validation_status": "not_available",
            "range": {
                "low": None,
                "high": None,
                "source": None,
                "unavailable_reason": "기권 판정으로 예정가격 범위를 제시하지 않았어요.",
            },
        },
        "bid_rate": {"at_mean": None},
        "tie_risk": None,
        "danger_zone": None,
        "recommendation": reason,
        "competition": None,
        "competition_unavailable_reason": "참여수 예측은 선택 기능이며 추천 판정과 분리돼 있어요.",
        "basis": None,
        "input": {
            "bid_no": req.bid_no,
            "base_amount": req.base_amount,
            "basis_status": req.basis_status,
            "a_value": req.a_value,
            "a_value_status": req.a_value_status,
            "lower_limit_rate": req.lower_limit_rate,
            "bid_date": _bid_date_text(req.bid_date),
            "prdprc_range_bgn": req.prdprc_range_bgn,
            "prdprc_range_end": req.prdprc_range_end,
            "bid_type": (req.bid_type or "").lower(),
            "bid_method": method,
            "contract_method": req.contract_method,
        },
    }


def _runtime_identity(
    strategy_parameters_hash: str | None,
) -> tuple[str, str, str]:
    """현재 추천 공식과 실행 코드를 버전 가능한 fingerprint로 식별한다.

    배포 환경이 commit SHA를 주입하면 그대로 쓰고, 그렇지 않으면 공식 source
    fingerprint를 명시적인 ``runtime-`` 식별자로 사용한다. 어느 경우에도
    출처를 evidence에 남겨 git SHA인 척하지 않는다.
    """
    import inspect

    from app.services import lower_limits
    from app.services.calculator import CalculatorService

    formula_hash = canonical_hash({
        # 가격 계산과 같은 active snapshot에서 반환된 hash다. 별도 active
        # 재조회나 정적 bootstrap hash를 쓰면 추천값과 증적이 갈라질 수 있다.
        "strategy_parameters_hash": strategy_parameters_hash,
        "recommend": inspect.getsource(CalculatorService.recommend_bid_price),
        "truncate": inspect.getsource(CalculatorService.truncate_to_10_won),
        "price_at_rate": inspect.getsource(CalculatorService.calculate_price_at_rate),
        "lower_limit": inspect.getsource(lower_limits.get_lower_limit_rate),
        "planned_price_range": inspect.getsource(_planned_price_range),
        "a_adjusted_price": inspect.getsource(_a_adjusted_price),
        "calculator_bid_rate": inspect.getsource(_calculator_bid_rate_pct),
    })
    injected_sha = next((
        value.strip()
        for key in ("BIDEASY_CODE_SHA", "GITHUB_SHA", "SOURCE_VERSION")
        if (value := os.getenv(key, "")).strip()
    ), None)
    if injected_sha:
        return injected_sha[:64], formula_hash, "deployment_environment"
    return f"runtime-{formula_hash[:56]}", formula_hash, "runtime_formula_fingerprint"


def _verified_strategy_deployment(
    db: Session,
    *,
    rec: dict[str, Any],
    route: BidRoute,
) -> dict[str, Any] | None:
    """Resolve the active rule to a deployed, route-scoped evidence chain.

    Legacy ``active.json`` files predate manifests and human approvals. They
    remain available as offline baselines, but must not be presented as a
    verified user recommendation until an ACTIVE deployment links the exact
    parameters, formula, code, dataset, G-C gate, and approval.
    """
    from app.db import models

    deployment = (
        db.query(models.AlgorithmDeployment)
        .filter(
            models.AlgorithmDeployment.route == route.value,
            models.AlgorithmDeployment.strategy_version == rec["strategy_version"],
            models.AlgorithmDeployment.status == "ACTIVE",
            models.AlgorithmDeployment.deployed_at.isnot(None),
        )
        .first()
    )
    if deployment is None:
        return None
    candidate = db.get(models.StrategyCandidate, deployment.candidate_id)
    gate = db.get(models.AlgorithmGateDecision, deployment.gate_decision_id)
    approval = db.get(models.AlgorithmApproval, deployment.approval_id)
    if candidate is None or gate is None or approval is None:
        return None
    now = _now_utc()

    def aware(value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=timezone.utc)

    approved_at = aware(approval.approved_at)
    expires_at = aware(approval.expires_at)
    code_sha, formula_hash, _source = _runtime_identity(
        rec.get("strategy_parameters_hash")
    )
    if (
        candidate.route != route.value
        or candidate.strategy_version != rec["strategy_version"]
        or candidate.parameters_hash != rec.get("strategy_parameters_hash")
        or not candidate.data_manifest_hash
        or candidate.code_sha != deployment.code_sha
        or candidate.code_sha != code_sha
        or candidate.formula_hash != formula_hash
        or gate.decision != "PASS"
        or gate.gate_name != "G-C"
        or gate.approval_id != approval.approval_id
        or approval.scope != "PROMOTION"
        or approval.status != "APPROVED"
        or approval.route != route.value
        or approval.strategy_version != rec["strategy_version"]
        or approved_at is None
        or approved_at > now
        or (expires_at is not None and expires_at <= now)
    ):
        return None
    return {
        "deployment_id": deployment.deployment_id,
        "candidate_id": candidate.candidate_id,
        "gate_decision_id": gate.decision_id,
        "approval_id": approval.approval_id,
        "data_manifest_hash": candidate.data_manifest_hash,
    }


def _record_decision(
    db: Session,
    *,
    req: SmartBidRequest,
    user_id: int,
    data: dict[str, Any],
    as_of: datetime,
) -> None:
    """사용자에게 돌려줄 decision과 같은 transaction으로 lineage를 기록한다."""
    code_sha, formula_hash, code_identity_source = _runtime_identity(
        data.get("strategy_parameters_hash")
    )
    data["as_of"] = _iso_utc(as_of)
    data["evidence"].update({
        "code_sha": code_sha,
        "formula_hash": formula_hash,
        "code_identity_source": code_identity_source,
    })

    unavailable_reason = data["probabilities"]["unavailable_reason"]
    policies = []
    if data["decision_status"] == "recommended":
        policies.append(RecommendationPolicy(
            name="balanced",
            price=int(data["optimal_bid"]),
            below_floor_probability=None,
            price_first_probability=None,
            final_award_probability=None,
            confidence=None,
            probability_unavailable_reason=unavailable_reason,
        ))

    recommendation_id = data["recommendation_id"]
    contract = RecommendationDecisionContract(
        recommendation_id=recommendation_id,
        notice_id=req.bid_no or f"unlinked:{recommendation_id}",
        as_of=as_of,
        route=data["route"],
        strategy_version=data["strategy_version"] or (
            "abstain:no_strategy"
            if data["decision_status"] == "abstained"
            else "runtime:unknown_strategy"
        ),
        data_manifest_hash=data.get("data_manifest_hash"),
        code_sha=code_sha,
        formula_hash=formula_hash,
        public_input_snapshot={
            "bid_no": req.bid_no,
            "basis_amount": req.base_amount,
            "basis_status": req.basis_status,
            "bid_type": req.bid_type,
            "bid_method": normalize_bid_method(req.bid_method),
            "contract_method": req.contract_method,
            "a_value": req.a_value,
            "a_value_status": req.a_value_status,
            "lower_limit_rate": req.lower_limit_rate,
            "agency_name": req.agency_name,
            "bid_date": _bid_date_text(req.bid_date),
            "prdprc_range_bgn": req.prdprc_range_bgn,
            "prdprc_range_end": req.prdprc_range_end,
        },
        policies=policies,
        abstain_reason=data["abstain_reason"],
        evidence=data["evidence"],
    )
    record_recommendation(db, contract, user_id=user_id)
    db.commit()


def _success_response(
    db: Session,
    *,
    req: SmartBidRequest,
    user_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    as_of = _now_utc()
    try:
        _record_decision(db, req=req, user_id=user_id, data=data, as_of=as_of)
    except Exception as exc:
        db.rollback()
        logger.exception("스마트 투찰 decision evidence 기록 실패")
        raise HTTPException(status_code=500, detail=_GENERIC_ERROR_MSG) from exc
    return {"status": "success", "data": data}


# ============================================================
# 1. 참여수 예측 (블루오션 탐지)
# ============================================================

@router.post("/competition/predict")
async def predict_competition(req: CompetitionPredictRequest, _user=Depends(require_tier("pro"))) -> Dict[str, Any]:
    """
    입찰 참여업체수 예측 및 블루오션 판별

    - 예상 참여업체수, 경쟁 강도, 블루오션 확률 반환
    - 기관별 과거 통계 포함
    """
    try:
        from app.services.participant_prediction_service import get_participant_prediction_service
        service = get_participant_prediction_service()

        bid_date = date.fromisoformat(req.bid_date) if req.bid_date else date.today()

        result = service.predict(
            bid_type=req.bid_type,
            estimated_amount=req.estimated_amount,
            agency_name=req.agency_name,
            bid_date=bid_date,
        )
        return {"status": "success", "data": result}

    except _UNAVAILABLE_ERRORS:
        raise HTTPException(status_code=503, detail="참여수 예측 기능은 현재 준비 중이에요.")
    except Exception:
        logger.exception("참여수 예측 실패")
        raise HTTPException(status_code=500, detail=_GENERIC_ERROR_MSG)


# ============================================================
# 2. 스마트 투찰 추천 (참여수 적응형)
# ============================================================

@router.post("/recommend")
async def get_smart_recommendation(
    req: SmartBidRequest,
    current_user=Depends(require_tier("pro_plus")),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    검증 범위 내 투찰가 후보 (autocalibrate 룰기반)

    2026-07-18: 죽은 ML 시뮬레이션(numpy 의존, 생산 500)을 검증된 자가보정
    룰기반(`recommend_bid_price`, 순수 Python)으로 대체. 낙찰가를 예측하지 않고,
    과거 개찰 데이터로 보정한 가격 후보를 제시한다.
    검증 표본이 공사 적격심사/소액수의견적에 한정되므로 그 밖의 route는
    가격을 꾸며내지 않고 200 + 명시적 abstain decision을 반환한다.
    """
    bid_type = (req.bid_type or "").lower()
    method = normalize_bid_method(req.bid_method)
    route = classify_bid_route(method, req.contract_method)

    if req.base_amount is None or (req.basis_status or "").lower() != "confirmed":
        return _success_response(
            db,
            req=req,
            user_id=current_user.id,
            data=_abstain_data(
                req,
                route=route,
                code="unconfirmed_basis_amount",
                reason="확인된 기초금액이 없어 추천가를 제시하지 않았어요.",
            ),
        )
    if method is None:
        return _success_response(
            db,
            req=req,
            user_id=current_user.id,
            data=_abstain_data(
                req,
                route=route,
                code="missing_bid_method",
                reason="입찰방법을 확인할 수 없어 추천가를 제시하지 않았어요.",
            ),
        )
    if bid_type != "construction":
        return _success_response(
            db,
            req=req,
            user_id=current_user.id,
            data=_abstain_data(
                req,
                route=route,
                code="unsupported_bid_type",
                reason="현재 검증된 추천 범위는 공사 공고예요. 물품·용역은 추천가를 제시하지 않아요.",
            ),
        )
    if (
        route not in {BidRoute.PRICE_DOMINANT, BidRoute.QUALIFICATION}
        or not supports_smart_bid(bid_type, method)
    ):
        return _success_response(
            db,
            req=req,
            user_id=current_user.id,
            data=_abstain_data(
                req,
                route=route,
                code="unsupported_bid_method",
                reason="이 입찰방법은 아직 검증된 전략이 없어 추천가를 제시하지 않았어요.",
            ),
        )
    if req.lower_limit_rate is None and req.bid_date is None:
        return _success_response(
            db,
            req=req,
            user_id=current_user.id,
            data=_abstain_data(
                req,
                route=route,
                code="missing_lower_limit_context",
                reason=(
                    "공고 낙찰하한율과 규칙 시행일을 확인할 수 없어 "
                    "추천가를 제시하지 않았어요."
                ),
            ),
        )
    if (req.a_value_status or "").lower() not in {
        "confirmed",
        "not_applicable",
    }:
        return _success_response(
            db,
            req=req,
            user_id=current_user.id,
            data=_abstain_data(
                req,
                route=route,
                code="unknown_a_value_status",
                reason=(
                    "A값 적용 여부 또는 확정 A값을 확인할 수 없어 "
                    "추천가를 제시하지 않았어요."
                ),
            ),
        )

    try:
        from app.services.calculator import CalculatorService

        rec = CalculatorService.recommend_bid_price(
            basic_price=req.base_amount,
            bid_method=method,
            contract_type="CONSTRUCTION",
            a_value=req.a_value or 0,
            lower_limit_rate=req.lower_limit_rate,
            bid_date=req.bid_date,
        )

        verified_deployment = _verified_strategy_deployment(
            db,
            rec=rec,
            route=route,
        )
        if verified_deployment is None:
            data = _abstain_data(
                req,
                route=route,
                code="unverified_strategy_lineage",
                reason=(
                    "현재 가격 전략을 데이터·독립 검증·사람 승인까지 "
                    "역추적할 수 없어 추천가를 제시하지 않았어요."
                ),
            )
            data["strategy_version"] = rec["strategy_version"]
            data["strategy_parameters_hash"] = rec["strategy_parameters_hash"]
            data["evidence"].update({
                "strategy_version": rec["strategy_version"],
                "strategy_parameters_hash": rec["strategy_parameters_hash"],
                "strategy_lineage_status": "UNVERIFIED",
            })
            return _success_response(
                db,
                req=req,
                user_id=current_user.id,
                data=data,
            )
        rec["data_manifest_hash"] = verified_deployment["data_manifest_hash"]

        lower_rate = rec["lower_limit_rate"]          # 예: 89.745 (%)
        margin = rec["margin"]
        predicted_reserved = rec["predicted_reserved_price"]
        # 예상 예정가 기준 가격 하한. A값을 제외한 변동분에만
        # 하한율을 적용하고 실제 투찰 규칙과 동일하게 10원 단위로 절사한다.
        danger_zone = _a_adjusted_price(
            predicted_reserved,
            lower_rate,
            req.a_value,
        )
        calculator_bid_rate = _calculator_bid_rate_pct(
            basic_price=req.base_amount,
            recommended_price=rec["recommended_price"],
            a_value=req.a_value,
        )
        planned_range = _planned_price_range(req)

        data = {
            "recommendation_id": str(uuid4()),
            "as_of": _iso_utc(_now_utc()),
            "route": route.value,
            "strategy_version": rec["strategy_version"],
            "strategy_parameters_hash": rec["strategy_parameters_hash"],
            "data_manifest_hash": rec.get("data_manifest_hash"),
            "decision_status": "recommended",
            "abstain_code": None,
            "abstain_reason": None,
            "evidence": {
                **_request_evidence(req, method, basis="autocalibrate_rule_based"),
                "strategy_parameters_hash": rec["strategy_parameters_hash"],
                "strategy_lineage_status": "VERIFIED_DEPLOYMENT",
                **verified_deployment,
            },
            "probabilities": _unverified_probabilities(),
            "optimal_bid": float(rec["recommended_price"]),
            "lower_limit": round(lower_rate / 100.0, 5),
            "lower_limit_pct": f"{lower_rate:.3f}%",
            "applied_margin_pct": margin,
            "effective_rate": rec["target_rate_pct"],
            "expected_planned_price": {
                "mean": round(predicted_reserved),
                "mean_validation_status": "rule_point_not_probability_calibrated",
                "range": planned_range,
            },
            "bid_rate": {
                # Flutter 계산기의 (basis-A)*rate+A 공식을 거꾸로 풀어
                # 추천가를 재현하는 적용률. 표시와 적용이 동일하다.
                "at_mean": calculator_bid_rate,
                "price_to_basis_pct": rec["bid_rate"],
            },
            "tie_risk": "high" if margin <= 0.05 else "medium",
            "danger_zone": danger_zone,
            "recommendation": (
                f"과거 개찰 데이터로 보정한 규칙 기반 가격 후보예요. "
                f"기초금액 대비 가격은 {rec['bid_rate']:.2f}%이며 계산상 하한율 "
                f"{lower_rate:.3f}% 위입니다. 하한미달, 입찰무효, 적격탈락, "
                "적자수주는 별도 확인이 필요하고 확률은 아직 검증되지 않았어요."
            ),
            "competition": None,        # 참여수 예측 ML 미탑재 — 정직하게 생략
            "competition_unavailable_reason": "참여수 예측은 선택 기능이며 추천 판정과 분리돼 있어요.",
            "basis": "autocalibrate_rule_based",
            "input": {
                "bid_no": req.bid_no,
                "base_amount": req.base_amount,
                "a_value": req.a_value,
                "lower_limit_rate": req.lower_limit_rate,
                "bid_date": _bid_date_text(req.bid_date),
                "prdprc_range_bgn": req.prdprc_range_bgn,
                "prdprc_range_end": req.prdprc_range_end,
                "bid_type": bid_type,
                "bid_method": method,
                "contract_method": req.contract_method,
            },
        }
        return _success_response(
            db,
            req=req,
            user_id=current_user.id,
            data=data,
        )

    except _UNAVAILABLE_ERRORS:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE_MSG)
    except Exception:
        logger.exception("스마트 투찰 추천 실패")
        raise HTTPException(status_code=500, detail=_GENERIC_ERROR_MSG)


# ============================================================
# 3. 유형별 낙찰률 예측
# ============================================================

@router.post("/rate/predict")
async def predict_bid_rate(req: BidRatePredictRequest, _user=Depends(require_tier("pro_plus"))) -> Dict[str, Any]:
    """
    유형별 낙찰률 예측

    - 물품/용역: ML 모델 기반 예측 (분산이 커서 효과적)
    - 공사: 참여수 기반 전략이 우선이므로 참고용
    """
    try:
        from app.services.bidrate_prediction_service import get_bidrate_prediction_service
        service = get_bidrate_prediction_service()

        bid_date = date.fromisoformat(req.bid_date) if req.bid_date else date.today()

        result = service.predict_bid_rate(
            bid_type=req.bid_type,
            estimated_amount=req.estimated_amount,
            expected_participants=req.expected_participants,
            agency_name=req.agency_name,
            bid_date=bid_date,
        )
        return {"status": "success", "data": result}

    except _UNAVAILABLE_ERRORS:
        raise HTTPException(status_code=503, detail="낙찰률 예측 기능은 현재 준비 중이에요.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("낙찰률 예측 실패")
        raise HTTPException(status_code=500, detail=_GENERIC_ERROR_MSG)


# ============================================================
# 4. 기관별 낙찰률 통계
# ============================================================

@router.get("/agency/stats")
async def get_agency_bid_stats(
    bid_type: str = Query(..., description="입찰 유형"),
    agency_name: str = Query("", description="기관명 (정확 매칭)"),
    keyword: str = Query("", description="기관명 검색어"),
    limit: int = Query(20, description="결과 수", ge=1, le=100),
) -> Dict[str, Any]:
    """
    기관별 과거 낙찰률 통계

    - 평균/중앙값 낙찰률, 표준편차, 평균 참여수, 총 입찰 건수
    - 키워드 검색 지원
    """
    try:
        from app.services.bidrate_prediction_service import get_bidrate_prediction_service
        service = get_bidrate_prediction_service()

        result = service.get_agency_statistics(
            bid_type=bid_type,
            agency_name=agency_name,
            keyword=keyword,
            limit=limit,
        )
        return {"status": "success", "data": result}

    except _UNAVAILABLE_ERRORS:
        raise HTTPException(status_code=503, detail="기관 통계 기능은 현재 준비 중이에요.")
    except Exception:
        logger.exception("기관 통계 조회 실패")
        raise HTTPException(status_code=500, detail=_GENERIC_ERROR_MSG)


@router.get("/agency/search")
async def search_agencies(
    keyword: str = Query(..., description="기관명 검색어", min_length=1),
    limit: int = Query(10, description="결과 수", ge=1, le=50),
) -> Dict[str, Any]:
    """기관명 검색 (참여수 예측용)"""
    try:
        from app.services.participant_prediction_service import get_participant_prediction_service
        service = get_participant_prediction_service()

        results = service.search_agencies(keyword=keyword, limit=limit)
        return {"status": "success", "data": results}

    except _UNAVAILABLE_ERRORS:
        raise HTTPException(status_code=503, detail="기관 검색 기능은 현재 준비 중이에요.")
    except Exception:
        logger.exception("기관 검색 실패")
        raise HTTPException(status_code=500, detail=_GENERIC_ERROR_MSG)


@router.get("/agency/insights")
async def get_agency_insights_endpoint(
    agency_name: str = Query(..., description="발주기관명"),
    bid_type: str = Query(None, description="입찰 유형 (construction, goods, service)"),
) -> Dict[str, Any]:
    """
    발주처 인사이트 — Historical DB 직접 조회

    - 평균/중앙값 낙찰률, 참여업체 수, 최근 트렌드
    - 전체 평균 대비 비교 + 한줄 인사이트
    """
    try:
        from app.services.organization_insights import get_agency_insights

        result = get_agency_insights(agency_name, bid_type)
        return {"status": "success", "data": result}

    except _UNAVAILABLE_ERRORS:
        raise HTTPException(status_code=503, detail="발주처 인사이트 기능은 현재 준비 중이에요.")
    except Exception:
        logger.exception("발주처 인사이트 조회 실패")
        raise HTTPException(status_code=500, detail=_GENERIC_ERROR_MSG)


# ============================================================
# 6. 투찰 역검증 ("왜 떨어졌을까?")
# ============================================================

@router.post("/verify")
async def verify_bid_result(req: BidVerifyRequest, _user=Depends(require_tier("pro"))) -> Dict[str, Any]:
    """
    투찰 역검증 — 내 투찰가를 입력하면 순위/편차/개선점 분석

    - 개찰 결과에서 해당 공고의 낙찰 데이터 조회
    - 사용자 투찰가 대비 순위, 편차, 한줄 분석
    """
    try:
        from app.services.bid_verifier import verify_bid

        result = verify_bid(
            bid_no=req.bid_no,
            my_bid_price=req.my_bid_price,
            basic_price=req.basic_price,
            organization=req.organization,
        )
        return {"status": "success", "data": result}

    except _UNAVAILABLE_ERRORS:
        raise HTTPException(status_code=503, detail="투찰 역검증 기능은 현재 준비 중이에요.")
    except Exception:
        logger.exception("투찰 역검증 실패")
        raise HTTPException(status_code=500, detail=_GENERIC_ERROR_MSG)


@router.get("/summary")
async def get_model_summary() -> Dict[str, Any]:
    """전체 모델 상태 요약"""
    summary = {}

    try:
        from app.services.participant_prediction_service import get_participant_prediction_service
        svc = get_participant_prediction_service()
        summary["participant_model"] = {
            "status": "ready",
            "accuracy": svc.metrics.get("classification", {}).get("accuracy", 0),
            "blue_ocean_accuracy": svc.metrics.get("classification", {}).get("binary_accuracy", 0),
        }
    except Exception as e:
        summary["participant_model"] = {"status": "unavailable", "error": str(e)}

    try:
        from app.services.bidrate_prediction_service import get_bidrate_prediction_service
        svc = get_bidrate_prediction_service()
        summary["bidrate_model"] = {
            "status": "ready",
            "types": svc.get_all_type_summary(),
        }
    except Exception as e:
        summary["bidrate_model"] = {"status": "unavailable", "error": str(e)}

    return {"status": "success", "data": summary}
