"""
현재 전략 사후 재생 서비스 — 진단 전용
=======================================
개찰 뒤 현재 전략을 과거 공고에 다시 적용하는 counterfactual 진단이다.
마감 전에 고정된 사용자 추천이 아니므로 성과 검증이나 자가보정 학습 증거로
사용하지 않는다. 실제 추천 성과는 RecommendationEvent 계보로만 측정한다.

호출처:
- CLI: scripts/verify_predictions.py (수동)
- Celery: app/tasks/verification_tasks.py:daily_verify_predictions (자동)

내부 학습 파이프라인:
1. opening_result_crawler 가 개찰 결과를 적재
2. 본 모듈이 현재 전략을 사후 재생
3. 결과를 COUNTERFACTUAL로 명시해 별도 진단 로그에 남김
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy.orm import Session

from app.db import models
from app.services import basis as basis_service
from app.services.bid_data_quality import base_is_consistent
from app.services.bid_route import classify_bid_route
from app.services.calculator import CalculatorService
from app.services.lower_limits import get_lower_limit_rate


@dataclass
class PolicyResult:
    """한 정책의 모의 입찰 결과."""

    label: str            # 'standard' / 'auto_recommended' / 'aggressive_mc'
    rate: float           # 적용된 사정률 (-2.5, etc.)
    price: int            # 우리 추천 투찰가
    passed_limit: bool    # 하한선 통과 여부
    won: bool             # 낙찰 여부
    diff_vs_winner: float # 우리 가격 - 실 낙찰가
    diff_pct: float       # 차이 %

    @property
    def result(self) -> str:
        if self.won:
            return "WIN"
        if not self.passed_limit:
            return "DROPOUT"
        return "LOST"

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "rate": self.rate,
            "price": self.price,
            "passed_limit": self.passed_limit,
            "won": self.won,
            "diff_vs_winner": round(self.diff_vs_winner, 0),
            "diff_pct": round(self.diff_pct, 3),
            "result": self.result,
        }


def compute_recommendations(notice: models.Notice) -> dict[str, dict]:
    """단일 notice 에 대해 현재 정책의 사후 counterfactual을 산출한다.

    1) standard       — 사용자 슬라이더 기본값 (사정률 -2.5%)
    2) auto_recommended — BID_STRATEGY 기반 자동 추천
    3) aggressive_mc  — 시장 평균 추격 (Monte Carlo 가설, -12%)
    """
    bp = basis_service.confirmed_basis(notice)
    if bp is None:
        return {}
    route = classify_bid_route(notice.bid_method, notice.contract_method)
    if route.value not in {"QUALIFICATION", "PRICE_DOMINANT"}:
        return {}
    if not notice.bid_method:
        return {}

    a_applicable = str(notice.a_value_applicable or "").upper()
    if a_applicable == "N":
        a_value = 0
    elif (notice.a_value or 0) > 0 and notice.a_value_source:
        a_value = int(notice.a_value)
    else:
        return {}

    lower_rate = float(notice.lower_limit_rate or 0) or None
    bid_date = notice.start_date.date() if notice.start_date else None
    if lower_rate is None:
        if (notice.contract_type or "").upper() != "CONSTRUCTION":
            return {}
        lower_rate = get_lower_limit_rate("CONSTRUCTION", bp, bid_date)

    std_rate = -2.5
    std_price = CalculatorService.calculate_safe_bid(
        basic_price=bp, rate=std_rate, a_value=a_value
    )

    auto = CalculatorService.recommend_bid_price(
        basic_price=bp,
        bid_method=notice.bid_method,
        contract_type=notice.contract_type or "CONSTRUCTION",
        a_value=a_value,
        lower_limit_rate=lower_rate,
        bid_date=bid_date,
    )

    mc_rate = -12.0
    mc_price = CalculatorService.calculate_safe_bid(
        basic_price=bp, rate=mc_rate, a_value=a_value
    )

    return {
        "standard": {"rate": std_rate, "price": std_price},
        "auto_recommended": {
            # recommend_bid_price 는 'recommended_price' 와 'bid_rate' 를 반환 (price/rate 아님)
            "rate": auto.get("bid_rate"),
            "price": auto.get("recommended_price"),
            "adjustment": auto.get("adjustment"),
            "margin": auto.get("margin"),
        },
        "aggressive_mc": {"rate": mc_rate, "price": mc_price},
    }


def evaluate_against_actual(
    notice: models.Notice,
    actual: models.OpeningResult,
) -> dict | None:
    """notice 에 대해 우리 추천 3가지 정책 vs 실 결과 비교 → 결과 dict.

    OpeningResult 의 winner_price/winner_rate 를 진실값으로 사용.
    하한율은 공사 금액대·시행일 티어드(단일 소스: lower_limits) 적용.
    실제 하한선은 reserved_price × lower_rate / 100 인데, reserved_price 가
    DB 에 있으면 그것 우선 사용.
    """
    if not actual or not actual.winner_price:
        return None

    bp = basis_service.confirmed_basis(notice)
    if bp is None:
        return None

    wp = float(actual.winner_price)
    wr = float(actual.winner_rate or 0) or (wp / bp * 100)

    # 하한율 — 공사 금액대·시행일 티어드 (검증 대상은 최근 30일 공고라 오늘 기준 적용)
    lower_rate = float(actual.lower_limit_rate or notice.lower_limit_rate or 0)
    if lower_rate <= 0:
        if (notice.contract_type or "").upper() != "CONSTRUCTION":
            return None
        bid_date = notice.start_date.date() if notice.start_date else None
        lower_rate = get_lower_limit_rate("CONSTRUCTION", bp, bid_date)

    # 실제 예정가격 없이 하한선을 추정하지 않는다.
    if not actual.reserved_price or actual.reserved_price <= 0:
        return None
    if not base_is_consistent(bp, actual.reserved_price):
        return None
    a_applicable = str(notice.a_value_applicable or "").upper()
    if a_applicable == "N":
        a_value = 0.0
    elif (notice.a_value or 0) > 0 and notice.a_value_source:
        a_value = float(notice.a_value)
    else:
        return None
    ll_price = (
        (float(actual.reserved_price) - a_value) * lower_rate / 100.0
    ) + a_value

    recs = compute_recommendations(notice)
    if not recs:
        return None

    def to_policy(label: str, data: dict) -> PolicyResult:
        price = data.get("price") or 0
        passed = price >= ll_price
        won = passed and price <= wp
        diff = price - wp
        diff_pct = (diff / wp * 100) if wp > 0 else 0.0
        return PolicyResult(
            label=label,
            rate=data.get("rate") or 0,
            price=price,
            passed_limit=passed,
            won=won,
            diff_vs_winner=diff,
            diff_pct=diff_pct,
        )

    policies = {label: to_policy(label, data).to_dict() for label, data in recs.items()}

    return {
        "bid_no": notice.bid_no,
        # 개찰 뒤 현재 전략을 재계산한 값이다. 마감 전 고정 추천의 성과가
        # 아니므로 VERIFIED prediction이나 낙찰률 증거로 집계하지 않는다.
        "status": "COUNTERFACTUAL",
        "evidence_kind": "post_opening_current_strategy_replay",
        "title": notice.title,
        "basic_price": bp,
        "bid_method": notice.bid_method,
        "opening_date": str(notice.opening_date) if notice.opening_date else None,
        "actual": {
            "winner_price": wp,
            "winner_rate": round(wr, 4),
            "reserved_price": float(actual.reserved_price) if actual.reserved_price else None,
            "estimated_lower_limit": round(ll_price, 0),
            "participants_count": actual.participants_count,
        },
        **policies,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def verify_notices(
    db: Session,
    notices: Iterable[models.Notice],
    log_path: Path | None = None,
) -> dict:
    """notices 리스트를 일괄 검증. log_path 가 있으면 JSONL 에 append.

    Returns:
        진단 통계 dict (counterfactual, pending, errors, per-policy counts).
    """
    bid_nos = [n.bid_no for n in notices]
    if not bid_nos:
        return {"verified": 0, "pending": 0, "errors": 0, "results": []}

    # opening_results 한 번에 조회 (N+1 회피)
    actual_map = {
        r.bid_no: r for r in
        db.query(models.OpeningResult).filter(
            models.OpeningResult.bid_no.in_(bid_nos)
        ).all()
    }

    results = []
    pending = 0
    errors = 0
    for n in notices:
        actual = actual_map.get(n.bid_no)
        if not actual:
            pending += 1
            results.append({
                "bid_no": n.bid_no,
                "status": "PENDING",
                "reason": "no opening result in DB",
                "verified_at": datetime.now(timezone.utc).isoformat(),
            })
            continue
        try:
            r = evaluate_against_actual(n, actual)
            if r is None:
                errors += 1
                continue
            results.append(r)
        except Exception as e:  # noqa: BLE001
            errors += 1
            results.append({
                "bid_no": n.bid_no,
                "status": "ERROR",
                "error": f"{type(e).__name__}: {e}",
                "verified_at": datetime.now(timezone.utc).isoformat(),
            })

    counterfactual_results = [
        r for r in results if r.get("status") == "COUNTERFACTUAL"
    ]

    # 집계
    def tally(key: str) -> tuple[int, int]:
        w = sum(1 for r in counterfactual_results if r[key]["won"])
        d = sum(
            1 for r in counterfactual_results if r[key]["result"] == "DROPOUT"
        )
        return w, d

    std_w, std_d = tally("standard")
    auto_w, auto_d = tally("auto_recommended")
    agg_w, agg_d = tally("aggressive_mc")

    # JSONL append
    if log_path and results:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")

    return {
        "verified": 0,
        "counterfactual": len(counterfactual_results),
        "pending": pending,
        "errors": errors,
        "policies": {
            "standard": {"wins": std_w, "dropouts": std_d},
            "auto_recommended": {"wins": auto_w, "dropouts": auto_d},
            "aggressive_mc": {"wins": agg_w, "dropouts": agg_d},
        },
        "results": results,
    }
