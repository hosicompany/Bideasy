"""
예측 검증 자동화 — Pre-launch 내부 테스트
=========================================

배경: 우리가 분석/계산한 공고에 대해 "실제 결과는 어땠는가" 를 자동으로
추적하고 정확도를 누적 측정. 자가보정 알고리즘의 핵심 입력 데이터가 된다.

사용 흐름:
    1. 크롤러가 공고를 DB notices 에 저장 (이미 운영 중)
    2. 사용자가 BidEasy 로 분석 (calculator/AI/scientific) → 우리가 "추천했을"
       시점의 추천가가 결정됨
    3. 개찰 후 데이터포털 낙찰정보 API 에서 실 결과 가져옴 (이미 OpeningResultService 있음)
    4. 본 스크립트: 우리 추천 vs 실 결과 비교 → predictions_log.jsonl 누적
    5. 자가보정 사이클이 predictions_log 데이터를 다음 학습 입력으로 사용

실행:
    docker compose ... exec app python scripts/verify_predictions.py
    docker compose ... exec app python scripts/verify_predictions.py --bid-no R26BK...
    docker compose ... exec app python scripts/verify_predictions.py --days 7
"""

import argparse
import json
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 백엔드 모듈 path 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal
from app.db import models
from app.services.opening_result import OpeningResultService
from app.services.calculator import CalculatorService, BID_STRATEGY


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LOG_PATH = DATA_DIR / "predictions_log.jsonl"
LOWER_LIMIT_RATE = 87.745  # 공사 기준


def calculate_our_recommendation(notice: models.Notice) -> dict:
    """BidEasy 표준 계산기 추천가 산출.

    실제 운영에서는 사용자가 사정률을 슬라이더로 선택하지만, 자동 검증을 위해
    BID_STRATEGY 기본값 (margin) 을 적용한 결과를 기록한다. 추후 'AI 추천',
    'Monte Carlo 추천', 'Blue Ocean 추천' 등을 추가로 비교할 수 있다.
    """
    bp = notice.basic_price or 0
    if bp <= 0:
        return None

    # BidEasy 표준 정책: 슬라이더 기본값 사정률 -2.5% (사용자가 만지지 않은 default)
    standard_rate = -2.5
    std_price = CalculatorService.calculate_safe_bid(
        basic_price=bp, rate=standard_rate, a_value=0
    )

    # BidEasy 자동 추천 (recommend_bid_price - BID_STRATEGY 기반)
    auto = CalculatorService.recommend_bid_price(
        basic_price=bp,
        bid_method=(notice.bid_method or "DEFAULT"),
        contract_type=notice.contract_type or "CONSTRUCTION",
    )

    # Monte Carlo 스타일 (모의 — 시장 평균 ~88.0% 가정)
    mc_rate = -12.0
    mc_price = math.floor(bp * (100 + mc_rate) / 100 / 10) * 10

    return {
        "standard": {  # 사용자 default 슬라이더 위치
            "rate": standard_rate,
            "price": std_price,
        },
        "auto_recommended": {  # BidEasy 자동 추천 (BID_STRATEGY)
            "rate": auto.get("rate"),
            "price": auto.get("price"),
            "adjustment": auto.get("adjustment"),
            "margin": auto.get("margin"),
        },
        "aggressive_mc": {  # 시장 평균 추격 가설
            "rate": mc_rate,
            "price": mc_price,
        },
    }


def fetch_opening_result(notice: models.Notice) -> dict | None:
    """data.go.kr 낙찰정보 API 호출 → 실 낙찰가.

    매핑되는 OpeningResult 데이터를 우선 사용. 없으면 API 직접 호출.
    실패 시 None.
    """
    db = SessionLocal()
    try:
        # DB 캐시 우선
        cached = db.query(models.OpeningResult).filter(
            models.OpeningResult.bid_no == notice.bid_no
        ).first()
        if cached and cached.winner_price:
            return {
                "winner_price": float(cached.winner_price),
                "winner_rate": float(cached.winner_rate or 0),
                "source": "db_cache",
            }
    finally:
        db.close()

    # API 호출
    try:
        results = OpeningResultService.fetch_opening_results(
            bid_no=notice.bid_no,
            contract_type=notice.contract_type or "CONSTRUCTION",
        )
        # mock 폴백 제외
        real = [r for r in results if "Mock" not in str(r.get("bidNtceNm", ""))]
        if not real:
            return None
        # 낙찰자 정보 추출 (API 응답 스키마는 OpeningResultService 코드 참조)
        first = real[0]
        wp = first.get("scsbidPrce") or first.get("winning_price") or 0
        try:
            wp = float(wp)
        except (TypeError, ValueError):
            return None
        if wp <= 0:
            return None
        bp = notice.basic_price or 0
        wr = (wp / bp * 100) if bp > 0 else 0
        return {
            "winner_price": wp,
            "winner_rate": round(wr, 4),
            "source": "data.go.kr_api",
        }
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def verify_one(notice: models.Notice) -> dict | None:
    """단일 공고 검증 — 우리 추천 vs 실 결과."""
    rec = calculate_our_recommendation(notice)
    if rec is None:
        return None

    actual = fetch_opening_result(notice)
    if actual is None:
        return {
            "bid_no": notice.bid_no,
            "status": "PENDING",
            "reason": "actual result not yet available",
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }
    if "error" in actual:
        return {
            "bid_no": notice.bid_no,
            "status": "ERROR",
            "error": actual["error"],
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }

    wp = actual["winner_price"]
    wr = actual["winner_rate"]
    bp = notice.basic_price or 1
    lower_limit_price = bp * LOWER_LIMIT_RATE / 100.0  # 단순 추정 (정확히는 reserved×lower_rate)

    def evaluate(policy: dict) -> dict:
        price = policy.get("price") or 0
        passed = price >= lower_limit_price
        won = passed and price <= wp
        diff = price - wp
        diff_pct = (diff / wp * 100) if wp > 0 else 0
        return {
            **policy,
            "passed_limit": passed,
            "won": won,
            "diff_vs_winner": round(diff, 0),
            "diff_pct": round(diff_pct, 3),
            "result": "WIN" if won else ("DROPOUT" if not passed else "LOST"),
        }

    return {
        "bid_no": notice.bid_no,
        "status": "VERIFIED",
        "title": notice.title,
        "basic_price": bp,
        "opening_date": notice.opening_date,
        "winner_price": wp,
        "winner_rate": wr,
        "estimated_lower_limit": round(lower_limit_price, 0),
        "standard": evaluate(rec["standard"]),
        "auto_recommended": evaluate(rec["auto_recommended"]),
        "aggressive_mc": evaluate(rec["aggressive_mc"]),
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "actual_source": actual.get("source"),
    }


def main():
    parser = argparse.ArgumentParser(description="예측 vs 실 결과 검증")
    parser.add_argument("--bid-no", help="특정 공고 1건만 검증")
    parser.add_argument("--days", type=int, default=30, help="최근 N일 내 개찰된 공고 (기본 30)")
    parser.add_argument("--limit", type=int, default=200, help="최대 검증 건수 (기본 200)")
    parser.add_argument("--no-save", action="store_true", help="결과를 JSONL 에 저장하지 않음 (드라이런)")
    args = parser.parse_args()

    db = SessionLocal()
    now = datetime.now()
    try:
        if args.bid_no:
            notices = db.query(models.Notice).filter(
                models.Notice.bid_no == args.bid_no
            ).all()
        else:
            # 개찰 일자가 과거이고 N일 이내인 공고
            cutoff = now - timedelta(days=args.days)
            notices = db.query(models.Notice).filter(
                models.Notice.end_date < now,
                models.Notice.end_date > cutoff,
            ).limit(args.limit).all()

        print(f"검증 대상: {len(notices)}건")
        print()

        results = []
        pending = 0
        verified = 0
        errors = 0

        for i, n in enumerate(notices, 1):
            print(f"[{i:3d}/{len(notices)}] {n.bid_no}  {(n.title or '')[:50]}")
            r = verify_one(n)
            if r is None:
                continue
            results.append(r)
            if r["status"] == "VERIFIED":
                verified += 1
                std = r["standard"]
                auto = r["auto_recommended"]
                agg = r["aggressive_mc"]
                print(f"             표준({std['result']:7s} {std['diff_pct']:+.2f}%)  "
                      f"자동({auto['result']:7s} {auto['diff_pct']:+.2f}%)  "
                      f"공격({agg['result']:7s} {agg['diff_pct']:+.2f}%)")
            elif r["status"] == "PENDING":
                pending += 1
                print("             (개찰 결과 없음 — 데이터 누적 대기)")
            else:
                errors += 1

        # JSONL 저장
        if not args.no_save and results:
            DATA_DIR.mkdir(exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8") as f:
                for r in results:
                    f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
            print()
            print(f"→ {LOG_PATH} 에 {len(results)}건 누적")

        # 집계
        if verified > 0:
            print()
            print("=" * 60)
            print("  집계")
            print("=" * 60)
            verified_results = [r for r in results if r.get("status") == "VERIFIED"]
            def tally(policy_key):
                w = sum(1 for r in verified_results if r[policy_key]["won"])
                d = sum(1 for r in verified_results if r[policy_key]["result"] == "DROPOUT")
                return w, d
            std_w, std_d = tally("standard")
            auto_w, auto_d = tally("auto_recommended")
            agg_w, agg_d = tally("aggressive_mc")
            print(f"  검증 완료:  {verified}건")
            print(f"  대기 중:    {pending}건")
            print(f"  에러:       {errors}건")
            print()
            print(f"  {'정책':<24}  {'낙찰':>10}  {'탈락':>10}")
            print(f"  {'-'*24}  {'-'*10}  {'-'*10}")
            print(f"  {'표준 -2.5% (default)':<24}  {std_w:>4} ({std_w/verified*100:>4.1f}%)  {std_d:>4} ({std_d/verified*100:>4.1f}%)")
            print(f"  {'자동 (BID_STRATEGY)':<24}  {auto_w:>4} ({auto_w/verified*100:>4.1f}%)  {auto_d:>4} ({auto_d/verified*100:>4.1f}%)")
            print(f"  {'공격 -12% (MC 가설)':<24}  {agg_w:>4} ({agg_w/verified*100:>4.1f}%)  {agg_d:>4} ({agg_d/verified*100:>4.1f}%)")

    finally:
        db.close()


if __name__ == "__main__":
    main()
