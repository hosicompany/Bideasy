"""
예측 검증 서비스 — Pre-launch 내부 자동 학습
============================================
사용자가 BidEasy 로 추천받은 가격이 실제 개찰 결과 대비 어떻게 성과를 냈는지
(낙찰/탈락/통과 후 짐) 자동 누적 측정. 자가보정 알고리즘의 핵심 입력 데이터.

호출처:
- CLI: scripts/verify_predictions.py (수동)
- Celery: app/tasks/verification_tasks.py:daily_verify_predictions (자동)

내부 학습 파이프라인:
1. 사용자가 BidEasy 분석 (calculator/AI) → 추천가 결정 (현재는 알고리즘만)
2. opening_result_crawler 가 매일 새 개찰 결과를 opening_results 테이블에 적재
3. 본 모듈: notices 와 opening_results 를 bid_no 로 조인 → 추천 vs 실제 비교
4. predictions_log.jsonl 에 누적
5. 매주 자가보정 사이클이 이 로그를 학습 입력으로 사용
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy.orm import Session

from app.db import models
from app.services.calculator import CalculatorService

_LOWER_LIMIT_RATE = 87.745  # 공사 기준


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
    """단일 notice 에 대해 BidEasy 가 추천했을 가격 3가지 산출.

    1) standard       — 사용자 슬라이더 기본값 (사정률 -2.5%)
    2) auto_recommended — BID_STRATEGY 기반 자동 추천
    3) aggressive_mc  — 시장 평균 추격 (Monte Carlo 가설, -12%)
    """
    bp = notice.basic_price or 0
    if bp <= 0:
        return {}

    std_rate = -2.5
    std_price = CalculatorService.calculate_safe_bid(basic_price=bp, rate=std_rate, a_value=0)

    auto = CalculatorService.recommend_bid_price(
        basic_price=bp,
        bid_method=(notice.bid_method or "DEFAULT"),
        contract_type=notice.contract_type or "CONSTRUCTION",
    )

    mc_rate = -12.0
    mc_price = math.floor(bp * (100 + mc_rate) / 100 / 10) * 10

    return {
        "standard": {"rate": std_rate, "price": std_price},
        "auto_recommended": {
            "rate": auto.get("rate"),
            "price": auto.get("price"),
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
    하한선 가격은 단순 추정 (basic_price × 87.745%).
    실제 하한선은 reserved_price × lower_rate / 100 인데, reserved_price 가
    DB 에 있으면 그것 우선 사용.
    """
    if not actual or not actual.winner_price:
        return None

    bp = float(notice.basic_price or 0)
    if bp <= 0:
        return None

    wp = float(actual.winner_price)
    wr = float(actual.winner_rate or 0) or (wp / bp * 100)

    # 하한선 가격 — reserved_price 가 있으면 정확 계산, 없으면 기초금액 기준 추정
    if actual.reserved_price and actual.reserved_price > 0:
        ll_price = float(actual.reserved_price) * _LOWER_LIMIT_RATE / 100.0
    else:
        ll_price = bp * _LOWER_LIMIT_RATE / 100.0

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
        "status": "VERIFIED",
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
        집계 통계 dict (verified, pending, errors, per-policy win/drop counts)
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

    verified_results = [r for r in results if r.get("status") == "VERIFIED"]

    # 집계
    def tally(key: str) -> tuple[int, int]:
        w = sum(1 for r in verified_results if r[key]["won"])
        d = sum(1 for r in verified_results if r[key]["result"] == "DROPOUT")
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
        "verified": len(verified_results),
        "pending": pending,
        "errors": errors,
        "policies": {
            "standard": {"wins": std_w, "dropouts": std_d},
            "auto_recommended": {"wins": auto_w, "dropouts": auto_d},
            "aggressive_mc": {"wins": agg_w, "dropouts": agg_d},
        },
        "results": results,
    }
