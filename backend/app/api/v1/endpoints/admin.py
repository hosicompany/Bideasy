"""
관리자 통계 엔드포인트
======================
자동 비교·자가보정 시스템의 성과를 운영자가 즉시 확인할 수 있는 통계 API.

접근 권한: tier=pro_plus 만 (`require_tier("pro_plus")`).
운영자 본인 계정(`hosicompany@gmail.com`)이 pro_plus 로 설정되어 있어서
별도 admin role 없이도 즉시 사용 가능.

Endpoints:
- GET /api/v1/admin/accuracy           — 전체·일별·정책별 정확도 통계
- GET /api/v1/admin/accuracy/recent    — 최근 검증된 N건 상세
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import require_tier
from app.db import models
from app.db.session import get_db
from app.schemas.subscription import TIER_PRO_PLUS

router = APIRouter()

_LOG_PATH = Path(__file__).resolve().parents[4] / "data" / "predictions_log.jsonl"


def _load_predictions_log() -> list[dict]:
    """predictions_log.jsonl 전체 로드. 없으면 빈 list."""
    if not _LOG_PATH.exists():
        return []
    records = []
    with _LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _tally_policies(verified: list[dict]) -> dict:
    """검증된 결과 list 에서 정책별 win/lost/dropout 집계."""
    policies = ["standard", "auto_recommended", "aggressive_mc"]
    out = {}
    n = len(verified)
    for p in policies:
        wins = sum(1 for r in verified if r.get(p, {}).get("won"))
        drops = sum(1 for r in verified if r.get(p, {}).get("result") == "DROPOUT")
        lost = n - wins - drops
        out[p] = {
            "total": n,
            "wins": wins,
            "dropouts": drops,
            "lost": lost,
            "win_rate": round(wins / n * 100, 2) if n else 0,
            "dropout_rate": round(drops / n * 100, 2) if n else 0,
        }
    return out


@router.get("/accuracy")
def get_accuracy(
    days: int = Query(30, ge=1, le=365, description="최근 N일 (기본 30)"),
    db: Session = Depends(get_db),
    _user=Depends(require_tier(TIER_PRO_PLUS)),
) -> dict[str, Any]:
    """전체·기간별·정책별 정확도 통계."""
    records = _load_predictions_log()
    verified = [r for r in records if r.get("status") == "VERIFIED"]
    pending = [r for r in records if r.get("status") == "PENDING"]
    errors = [r for r in records if r.get("status") == "ERROR"]

    # 최근 N일 (verified_at 기준)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    recent = [r for r in verified if r.get("verified_at", "") >= cutoff]

    # bid_method 별
    by_method: dict[str, list[dict]] = defaultdict(list)
    for r in verified:
        method = (r.get("bid_method") or "(unknown)").strip()
        by_method[method].append(r)

    # DB 인프라 통계
    db_stats = {
        "notices_total": db.query(models.Notice).count(),
        "opening_results_total": db.query(models.OpeningResult).count(),
        "users_total": db.query(models.User).count(),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db": db_stats,
        "predictions_log": {
            "total_records": len(records),
            "verified": len(verified),
            "pending": len(pending),
            "errors": len(errors),
        },
        "all_time": {
            "policies": _tally_policies(verified),
        },
        "recent": {
            "days": days,
            "verified": len(recent),
            "policies": _tally_policies(recent),
        },
        "by_bid_method": {
            method: {
                "count": len(items),
                "policies": _tally_policies(items),
            }
            for method, items in sorted(by_method.items(), key=lambda kv: -len(kv[1]))
        },
    }


@router.get("/accuracy/recent")
def get_recent_verified(
    limit: int = Query(20, ge=1, le=200, description="최근 검증된 N건 (기본 20)"),
    _user=Depends(require_tier(TIER_PRO_PLUS)),
) -> dict[str, Any]:
    """최근 검증된 입찰 N건의 상세 정보 (스토리텔링용)."""
    records = _load_predictions_log()
    verified = [r for r in records if r.get("status") == "VERIFIED"]
    # 최신 순 정렬
    verified.sort(key=lambda r: r.get("verified_at", ""), reverse=True)
    return {
        "count": len(verified[:limit]),
        "items": verified[:limit],
    }


@router.get("/opening-results/recent")
def get_recent_opening_results(
    limit: int = Query(20, ge=1, le=100, description="최근 적재된 N건 (기본 20)"),
    db: Session = Depends(get_db),
    _user=Depends(require_tier(TIER_PRO_PLUS)),
) -> dict[str, Any]:
    """최근 적재된 opening_results 목록 — 크롤러 작동 확인용."""
    rows = (
        db.query(models.OpeningResult)
        .order_by(models.OpeningResult.crawled_at.desc())
        .limit(limit)
        .all()
    )
    items = [
        {
            "bid_no": r.bid_no,
            "organization": r.organization,
            "bid_method": r.bid_method,
            "basic_price": r.basic_price,
            "reserved_price": r.reserved_price,
            "winner_price": r.winner_price,
            "winner_rate": r.winner_rate,
            "winner_company": r.winner_company,
            "open_date": str(r.open_date) if r.open_date else None,
            "crawled_at": str(r.crawled_at) if r.crawled_at else None,
        }
        for r in rows
    ]
    return {"count": len(items), "items": items}
