"""creative_id 기준 온라인 활성화 퍼널과 반복 사용 집계."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import require_admin
from app.db import models
from app.db.session import get_db


router = APIRouter()
FUNNEL_EVENTS = (
    "qualified_visit",
    "free_value_completed",
    "chrome_install_clicked",
    "notice_check_completed",
)


def _identity(row: models.GrowthEvent) -> str:
    if row.user_id is not None:
        return f"u:{row.user_id}"
    if row.anonymous_id:
        return f"a:{row.anonymous_id}"
    return f"event:{row.id}"


@router.get("/growth/creative-funnel")
def creative_funnel(
    days: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    rows = (
        db.query(models.GrowthEvent)
        .filter(models.GrowthEvent.occurred_at >= since)
        .order_by(models.GrowthEvent.occurred_at.asc())
        .all()
    )
    briefs = {
        brief.id: brief
        for brief in db.query(models.CreativeBrief).all()
    }

    identities: dict[str | None, dict[str, set[str]]] = defaultdict(
        lambda: {event: set() for event in FUNNEL_EVENTS}
    )
    raw_counts: dict[str | None, dict[str, int]] = defaultdict(
        lambda: {event: 0 for event in FUNNEL_EVENTS}
    )
    active_user_ids: set[int] = set()
    for row in rows:
        if row.event_name in FUNNEL_EVENTS:
            identities[row.creative_id][row.event_name].add(_identity(row))
            raw_counts[row.creative_id][row.event_name] += 1
        if row.event_name == "notice_check_completed" and row.user_id is not None and row.bid_no:
            active_user_ids.add(row.user_id)

    # 28일 반복 여부의 기준점은 조회 구간 안의 첫 행이 아니라 사용자의 실제 최초
    # 공고 확인이다. 예: 100일 전 첫 확인 후 최근 2건을 본 사용자를 "28일 내 반복"으로
    # 잘못 세지 않도록, 조회 구간에서 활성인 사용자들의 전체 공고 확인 이력을 읽는다.
    notice_by_user: dict[int, list[models.GrowthEvent]] = defaultdict(list)
    if active_user_ids:
        all_notice_rows = (
            db.query(models.GrowthEvent)
            .filter(
                models.GrowthEvent.event_name == "notice_check_completed",
                models.GrowthEvent.user_id.in_(active_user_ids),
                models.GrowthEvent.bid_no.isnot(None),
            )
            .order_by(models.GrowthEvent.occurred_at.asc())
            .all()
        )
        for row in all_notice_rows:
            notice_by_user[row.user_id].append(row)

    creative_ids = sorted(set(identities) | set(briefs), key=lambda value: value or "")
    items = []
    for creative_id in creative_ids:
        brief = briefs.get(creative_id) if creative_id else None
        counts = {event: len(identities[creative_id][event]) for event in FUNNEL_EVENTS}
        qualified = counts["qualified_visit"]
        activated = counts["notice_check_completed"]
        items.append({
            "creative_id": creative_id,
            "campaign_key": brief.campaign_key if brief else None,
            "concept_key": brief.concept_key if brief else None,
            "variant": brief.variant if brief else None,
            "status": brief.status if brief else None,
            "unique": counts,
            "raw": raw_counts[creative_id],
            "activation_rate_pct": round(activated / qualified * 100, 1) if qualified else None,
        })

    repeat_users = 0
    review_eligible_users = 0
    for user_rows in notice_by_user.values():
        bid_nos = {row.bid_no for row in user_rows}
        dates = {row.occurred_at.date() for row in user_rows if row.occurred_at}
        first = min((row.occurred_at for row in user_rows if row.occurred_at), default=None)
        within_28 = [
            row for row in user_rows
            if first is not None and row.occurred_at is not None and row.occurred_at <= first + timedelta(days=28)
        ]
        if len({row.bid_no for row in within_28}) >= 2 and len({row.occurred_at.date() for row in within_28}) >= 2:
            repeat_users += 1
        if len(bid_nos) >= 3 and len(dates) >= 2:
            review_eligible_users += 1

    return {
        "days": days,
        "generated_at": now.isoformat(),
        "items": items,
        "overall": {
            "target_active_users": 10,
            "active_users": len(active_user_ids),
            "target_repeat_users_28d": 4,
            "repeat_users_28d": repeat_users,
            "review_eligible_users": review_eligible_users,
        },
    }
