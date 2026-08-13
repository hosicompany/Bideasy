"""Versioned contracts for bid-algorithm evidence and user outcomes."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class BidRoute(str, Enum):
    PRICE_DOMINANT = "PRICE_DOMINANT"
    QUALIFICATION = "QUALIFICATION"
    COMPREHENSIVE = "COMPREHENSIVE"
    NEGOTIATION = "NEGOTIATION"
    UNSUPPORTED = "UNSUPPORTED"


class ExperimentManifestContract(BaseModel):
    experiment_id: str = Field(min_length=1, max_length=64)
    as_of_cutoff: datetime
    data_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_sha: str = Field(min_length=7, max_length=64)
    formula_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    route: BidRoute
    feature_whitelist: list[str]
    temporal_folds: dict[str, Any]
    baselines: list[str]
    metrics: list[str]
    minimum_practical_effect: dict[str, float]
    stop_rules: dict[str, Any]
    approval_id: str | None = None

    @model_validator(mode="after")
    def temporal_contract_is_complete(self):
        required = {"train", "validation", "sealed_test"}
        if not required.issubset(self.temporal_folds):
            missing = sorted(required - set(self.temporal_folds))
            raise ValueError(f"temporal_folds missing: {', '.join(missing)}")
        return self


class RecommendationPolicy(BaseModel):
    name: Literal["conservative", "balanced", "aggressive"]
    price: int = Field(gt=0)
    below_floor_probability: float | None = Field(default=None, ge=0, le=1)
    price_first_probability: float | None = Field(default=None, ge=0, le=1)
    final_award_probability: float | None = Field(default=None, ge=0, le=1)
    expected_profit: float | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    probability_unavailable_reason: str | None = None

    @model_validator(mode="after")
    def unexplained_null_probabilities_are_forbidden(self):
        values = (
            self.below_floor_probability,
            self.price_first_probability,
            self.final_award_probability,
            self.confidence,
        )
        if any(value is None for value in values) and not self.probability_unavailable_reason:
            raise ValueError("null probability/confidence requires probability_unavailable_reason")
        return self


class RecommendationDecisionContract(BaseModel):
    recommendation_id: str = Field(min_length=1, max_length=64)
    notice_id: str = Field(min_length=1, max_length=100)
    as_of: datetime
    route: BidRoute
    strategy_version: str = Field(min_length=1, max_length=80)
    data_manifest_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    code_sha: str = Field(min_length=7, max_length=64)
    formula_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_input_snapshot: dict[str, Any]
    policies: list[RecommendationPolicy] = Field(default_factory=list, max_length=3)
    abstain_reason: str | None = Field(default=None, max_length=80)
    evidence: dict[str, Any]

    @model_validator(mode="after")
    def policies_xor_abstention(self):
        if bool(self.policies) == bool(self.abstain_reason):
            raise ValueError("provide policies or abstain_reason, but not both")
        if self.policies and self.data_manifest_hash is None:
            raise ValueError("a recommendation policy requires verified dataset lineage")
        return self


class UserDecisionCreate(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=120)
    event_type: Literal[
        "EXPOSED",
        "APPLIED",
        "COPIED",
        "OVERRIDDEN",
        "SUBMITTED",
        "OUTCOME_LINKED",
    ]
    selected_policy: Literal["conservative", "balanced", "aggressive"] | None = None
    submitted_price: int | None = Field(default=None, gt=0)
    details: dict[str, Any] | None = None
    central_training_opt_in: bool = False
    occurred_at: datetime | None = None

    @model_validator(mode="after")
    def submission_requires_price(self):
        if self.event_type == "SUBMITTED" and self.submitted_price is None:
            raise ValueError("SUBMITTED requires submitted_price")
        return self


class UserDecisionResponse(BaseModel):
    id: int
    recommendation_id: str
    event_type: str
    occurred_at: datetime
    duplicate: bool = False


class CompetitorObservationContract(BaseModel):
    observation_id: str = Field(min_length=1, max_length=64)
    provider: Literal["DIMA", "KBID", "BIDPRO"]
    plan_tier: str | None = Field(default=None, max_length=80)
    notice_id: str = Field(min_length=1, max_length=100)
    as_of_cutoff: datetime
    observed_at: datetime
    deadline_at: datetime
    recommendation_price: int | None = Field(default=None, gt=0)
    recommendation_low: int | None = Field(default=None, gt=0)
    recommendation_high: int | None = Field(default=None, gt=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    abstain_reason: str | None = None
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_uri: str = Field(min_length=1, max_length=500)
    terms_scope: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def observation_precedes_deadline(self):
        if self.as_of_cutoff > self.observed_at:
            raise ValueError("observed_at must be at or after as_of_cutoff")
        if self.observed_at >= self.deadline_at:
            raise ValueError("competitor observation must be captured before deadline")
        if self.recommendation_price is None and not self.abstain_reason:
            raise ValueError("missing recommendation requires abstain_reason")
        return self
