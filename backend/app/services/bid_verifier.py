"""
투찰 역검증 서비스
"왜 떨어졌을까?" — 사용자 투찰가를 기반으로 순위/편차/개선점 분석
"""

import json
import sqlite3
from pathlib import Path
from typing import Optional

from app.core.logging import get_logger

logger = get_logger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / "data" / "historical" / "bid_results_5years.db"


def verify_bid(
    bid_no: str,
    my_bid_price: float,
    basic_price: float,
    organization: str = "",
) -> dict:
    """
    내 투찰가를 개찰 결과와 비교 분석

    Returns:
        my_rate: 내 투찰률 (%)
        winning_rate: 낙찰률 (%)
        winning_price: 낙찰가 (원)
        gap: 차이 (%p)
        total_participants: 총 참여업체
        my_rank: 내 예상 순위
        winner_name: 낙찰 업체명
        analysis: 분석 코멘트
        tip: 발주처 기반 팁
    """
    if basic_price <= 0:
        return {"error": "기초금액이 0 이하입니다."}

    my_rate = round((my_bid_price / basic_price) * 100, 4)

    # 1. Try to find in historical DB
    historical = _find_in_historical(bid_no)

    if historical:
        return _analyze_with_historical(
            my_rate, my_bid_price, basic_price, historical, organization
        )

    # 2. Fallback: try opening results API
    try:
        from app.services.opening_result import OpeningResultService

        results = OpeningResultService.fetch_opening_results(bid_no)
        if results:
            return _analyze_with_opening_results(
                my_rate, my_bid_price, basic_price, results, organization
            )
    except Exception as e:
        logger.warning(f"Opening results fetch failed: {e}")

    # 3. No data available
    return {
        "found": False,
        "my_rate": my_rate,
        "message": "이 공고의 개찰 결과를 찾을 수 없습니다.",
    }


def _find_in_historical(bid_no: str) -> Optional[dict]:
    """Historical DB에서 해당 공고 결과 검색"""
    if not DB_PATH.exists():
        return None

    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # bid_ntce_no로 검색
        cursor.execute(
            """SELECT bid_ntce_nm, dminstt_nm, sucsfbid_amt, sucsfbid_rate,
                      sucsfbid_corp_nm, bsis_amt, data_json
            FROM bid_results
            WHERE bid_ntce_no = ? AND sucsfbid_rate > 50 AND sucsfbid_rate <= 100
            LIMIT 1""",
            (bid_no,),
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        data_json = {}
        if row["data_json"]:
            try:
                data_json = json.loads(row["data_json"])
            except (json.JSONDecodeError, TypeError):
                pass

        return {
            "title": row["bid_ntce_nm"],
            "organization": row["dminstt_nm"],
            "winning_price": row["sucsfbid_amt"],
            "winning_rate": row["sucsfbid_rate"],
            "winner_name": row["sucsfbid_corp_nm"],
            "base_amount": row["bsis_amt"],
            "participants": data_json.get("prtcptCnum"),
        }

    except Exception as e:
        logger.error(f"Historical DB query error: {e}")
        return None


def _analyze_with_historical(
    my_rate: float,
    my_bid_price: float,
    basic_price: float,
    historical: dict,
    organization: str,
) -> dict:
    """Historical DB 데이터로 분석"""
    winning_rate = historical["winning_rate"]
    winning_price = historical["winning_price"]
    winner_name = historical["winner_name"] or "정보 없음"
    participants = None

    try:
        if historical["participants"]:
            participants = int(historical["participants"])
    except (ValueError, TypeError):
        pass

    gap = round(my_rate - winning_rate, 4)

    # Estimate rank
    my_rank = _estimate_rank(my_rate, winning_rate, participants)

    # Generate analysis comment
    analysis = _generate_analysis(my_rate, winning_rate, gap, my_rank, participants)

    # Generate org-based tip
    tip = _generate_tip(organization or historical.get("organization", ""))

    return {
        "found": True,
        "my_rate": my_rate,
        "my_bid_price": my_bid_price,
        "winning_rate": winning_rate,
        "winning_price": winning_price,
        "winner_name": winner_name,
        "gap": gap,
        "total_participants": participants,
        "my_rank": my_rank,
        "analysis": analysis,
        "tip": tip,
    }


def _analyze_with_opening_results(
    my_rate: float,
    my_bid_price: float,
    basic_price: float,
    results: list,
    organization: str,
) -> dict:
    """개찰 결과 API 데이터로 분석"""
    if not results:
        return {"found": False, "my_rate": my_rate, "message": "개찰 결과가 없습니다."}

    # Find winning bid
    winner = results[0] if isinstance(results[0], dict) else None
    if not winner:
        return {"found": False, "my_rate": my_rate, "message": "개찰 결과 파싱 실패"}

    winning_price = winner.get("bid_price", 0)
    winning_rate = winner.get("bid_rate", 0)
    winner_name = winner.get("company", "정보 없음")
    total_participants = len(results)

    # If winning_rate is 0, calculate from basic_price
    if winning_rate == 0 and basic_price > 0 and winning_price > 0:
        winning_rate = round((winning_price / basic_price) * 100, 4)

    gap = round(my_rate - winning_rate, 4)

    # Calculate actual rank among results
    my_rank = 1
    for r in results:
        r_price = r.get("bid_price", 0) if isinstance(r, dict) else 0
        if r_price > 0:
            r_rate = (r_price / basic_price) * 100
            # Closer to winning rate = better rank
            if abs(r_rate - winning_rate) < abs(my_rate - winning_rate):
                my_rank += 1

    analysis = _generate_analysis(
        my_rate, winning_rate, gap, my_rank, total_participants
    )
    tip = _generate_tip(organization)

    return {
        "found": True,
        "my_rate": my_rate,
        "my_bid_price": my_bid_price,
        "winning_rate": winning_rate,
        "winning_price": winning_price,
        "winner_name": winner_name,
        "gap": gap,
        "total_participants": total_participants,
        "my_rank": my_rank,
        "analysis": analysis,
        "tip": tip,
    }


def _estimate_rank(
    my_rate: float, winning_rate: float, participants: Optional[int]
) -> Optional[int]:
    """투찰률 차이로 예상 순위 추정"""
    if participants is None:
        return None

    gap = abs(my_rate - winning_rate)

    if gap < 0.01:
        return 1
    elif gap < 0.1:
        return max(1, int(participants * 0.05))
    elif gap < 0.3:
        return max(2, int(participants * 0.15))
    elif gap < 0.5:
        return max(3, int(participants * 0.3))
    elif gap < 1.0:
        return max(4, int(participants * 0.5))
    else:
        return max(5, int(participants * 0.7))


def _generate_analysis(
    my_rate: float,
    winning_rate: float,
    gap: float,
    my_rank: Optional[int],
    participants: Optional[int],
) -> str:
    """분석 코멘트 생성"""
    abs_gap = abs(gap)

    if abs_gap < 0.05:
        msg = "거의 낙찰에 근접했어요! 아주 미세한 차이였어요."
    elif abs_gap < 0.3:
        msg = f"{abs_gap:.2f}%p 차이로 아쉽게 놓치셨어요."
    elif abs_gap < 1.0:
        direction = "높게" if gap > 0 else "낮게"
        msg = f"낙찰가 대비 {abs_gap:.2f}%p {direction} 투찰하셨어요."
    else:
        direction = "높게" if gap > 0 else "낮게"
        msg = f"낙찰가와 {abs_gap:.1f}%p 차이가 있었어요. 상당히 {direction} 투찰하셨네요."

    if gap > 0:
        msg += " 투찰률을 조금 낮추면 낙찰 확률이 높아져요."
    elif gap < -0.5:
        msg += " 투찰률을 높이는 것을 고려해보세요."

    if my_rank and participants and my_rank <= 3:
        msg += f" {participants}개사 중 상위권이었어요!"

    return msg


def _generate_tip(organization: str) -> str:
    """발주처 기반 팁 생성"""
    if not organization:
        return "다음 투찰 시 발주처의 과거 낙찰 패턴을 확인해보세요."

    try:
        from app.services.organization_insights import get_agency_insights

        insights = get_agency_insights(organization)
        if insights.get("found"):
            avg = insights["avg_rate"]
            return f"이 발주처({organization})는 평균 {avg}%에서 낙찰되는 경향이 있어요."
    except Exception:
        pass

    return f"{organization}의 과거 낙찰 패턴을 확인해보세요."
