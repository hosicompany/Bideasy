"""
발주처 인사이트 서비스
bid_results_5years.db에서 직접 발주처별 통계를 조회
"""

import json
import sqlite3
import statistics
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.core.logging import get_logger

logger = get_logger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / "data" / "historical" / "bid_results_5years.db"


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


@lru_cache(maxsize=256)
def get_agency_insights(agency_name: str, bid_type: Optional[str] = None) -> dict:
    """
    발주처별 과거 실적 통계 조회

    Returns:
        avg_rate, median_rate, min_rate, max_rate, std_rate,
        total_bids, avg_participants, recent_6m_count,
        rate_trend ("rising"/"falling"/"stable"),
        insight (한줄 요약 코멘트)
    """
    if not DB_PATH.exists():
        logger.warning(f"Historical DB not found: {DB_PATH}")
        return {"error": "historical_db_not_found"}

    try:
        conn = _get_connection()
        cursor = conn.cursor()

        # Base filter
        where = "dminstt_nm = ? AND sucsfbid_rate > 50 AND sucsfbid_rate <= 100"
        params: list = [agency_name]

        if bid_type:
            where += " AND bid_type = ?"
            params.append(bid_type)

        # 1. Basic stats
        cursor.execute(
            f"""SELECT
                COUNT(*) as cnt,
                AVG(sucsfbid_rate) as avg_rate,
                MIN(sucsfbid_rate) as min_rate,
                MAX(sucsfbid_rate) as max_rate
            FROM bid_results WHERE {where}""",
            params,
        )
        row = cursor.fetchone()
        total_bids = row["cnt"]

        if total_bids == 0:
            # Try partial match
            like_where = where.replace("dminstt_nm = ?", "dminstt_nm LIKE ?")
            like_params = [f"%{agency_name}%"] + params[1:]

            cursor.execute(
                f"""SELECT
                    COUNT(*) as cnt,
                    AVG(sucsfbid_rate) as avg_rate,
                    MIN(sucsfbid_rate) as min_rate,
                    MAX(sucsfbid_rate) as max_rate
                FROM bid_results WHERE {like_where}""",
                like_params,
            )
            row = cursor.fetchone()
            total_bids = row["cnt"]
            if total_bids == 0:
                conn.close()
                return {
                    "found": False,
                    "agency_name": agency_name,
                    "message": "해당 발주처의 과거 데이터가 없습니다.",
                }
            # Update params for subsequent queries
            where = like_where
            params = like_params

        avg_rate = round(row["avg_rate"], 2)
        min_rate = round(row["min_rate"], 2)
        max_rate = round(row["max_rate"], 2)

        # 2. Median + std (fetch all rates)
        cursor.execute(
            f"SELECT sucsfbid_rate FROM bid_results WHERE {where}",
            params,
        )
        all_rates = [r["sucsfbid_rate"] for r in cursor.fetchall()]
        median_rate = round(statistics.median(all_rates), 2)
        std_rate = round(statistics.stdev(all_rates), 2) if len(all_rates) > 1 else 0.0

        # 3. Average participants (from JSON)
        cursor.execute(
            f"SELECT data_json FROM bid_results WHERE {where} AND data_json IS NOT NULL",
            params,
        )
        participant_counts = []
        for r in cursor.fetchall():
            try:
                data = json.loads(r["data_json"])
                prtcpt = data.get("prtcptCnum")
                if prtcpt and int(prtcpt) > 0:
                    participant_counts.append(int(prtcpt))
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

        avg_participants = (
            round(statistics.median(participant_counts), 1)
            if participant_counts
            else None
        )

        # 4. Recent 6 months count
        six_months_ago = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
        cursor.execute(
            f"""SELECT COUNT(*) as cnt FROM bid_results
            WHERE {where} AND json_extract(data_json, '$.rlOpengDt') >= ?""",
            params + [six_months_ago],
        )
        recent_6m_count = cursor.fetchone()["cnt"]

        # 5. Trend: compare recent 6m avg vs older avg
        rate_trend = "stable"
        if recent_6m_count >= 3:
            cursor.execute(
                f"""SELECT AVG(sucsfbid_rate) as recent_avg FROM bid_results
                WHERE {where} AND json_extract(data_json, '$.rlOpengDt') >= ?""",
                params + [six_months_ago],
            )
            recent_avg = cursor.fetchone()["recent_avg"]

            cursor.execute(
                f"""SELECT AVG(sucsfbid_rate) as old_avg FROM bid_results
                WHERE {where} AND (
                    json_extract(data_json, '$.rlOpengDt') < ?
                    OR json_extract(data_json, '$.rlOpengDt') IS NULL
                )""",
                params + [six_months_ago],
            )
            old_row = cursor.fetchone()
            old_avg = old_row["old_avg"] if old_row["old_avg"] else avg_rate

            diff = recent_avg - old_avg
            if diff > 0.3:
                rate_trend = "rising"
            elif diff < -0.3:
                rate_trend = "falling"

        # 6. Global average for comparison
        type_filter = "AND bid_type = ?" if bid_type else ""
        type_params = [bid_type] if bid_type else []
        cursor.execute(
            f"""SELECT AVG(sucsfbid_rate) as global_avg FROM bid_results
            WHERE sucsfbid_rate > 50 AND sucsfbid_rate <= 100 {type_filter}""",
            type_params,
        )
        global_avg = cursor.fetchone()["global_avg"]
        diff_from_global = round(avg_rate - global_avg, 2)

        conn.close()

        # 7. Generate insight comment
        insight = _generate_insight(
            avg_rate, global_avg, avg_participants, rate_trend, total_bids
        )

        return {
            "found": True,
            "agency_name": agency_name,
            "avg_rate": avg_rate,
            "median_rate": median_rate,
            "min_rate": min_rate,
            "max_rate": max_rate,
            "std_rate": std_rate,
            "total_bids": total_bids,
            "avg_participants": avg_participants,
            "recent_6m_count": recent_6m_count,
            "rate_trend": rate_trend,
            "diff_from_global": diff_from_global,
            "insight": insight,
        }

    except Exception as e:
        logger.error(f"Organization insights error: {e}")
        return {"error": str(e)}


def _generate_insight(
    avg_rate: float,
    global_avg: float,
    avg_participants: Optional[float],
    trend: str,
    total_bids: int,
) -> str:
    """한줄 인사이트 코멘트 생성"""
    parts = []

    diff = avg_rate - global_avg
    if diff > 1.0:
        parts.append(f"전체 평균보다 낙찰률이 {diff:.1f}%p 높은 편이에요")
    elif diff < -1.0:
        parts.append(f"전체 평균보다 낙찰률이 {abs(diff):.1f}%p 낮은 편이에요")
    else:
        parts.append("전체 평균과 비슷한 낙찰률이에요")

    if avg_participants:
        if avg_participants <= 10:
            parts.append("경쟁이 비교적 적은 발주처예요")
        elif avg_participants >= 30:
            parts.append("경쟁이 치열한 발주처예요")

    if trend == "rising":
        parts.append("최근 낙찰률이 상승 추세예요")
    elif trend == "falling":
        parts.append("최근 낙찰률이 하락 추세예요")

    if total_bids < 10:
        parts.append("데이터가 적어 참고용으로만 활용하세요")

    return ". ".join(parts) + "."


def clear_cache():
    """LRU cache clear (for testing)"""
    get_agency_insights.cache_clear()
