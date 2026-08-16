"""메시지 이해도 테스트의 사전등록 게이트 집계."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.endpoints.message_validation import CAMPAIGN_KEY, summarize_rows
from app.core.security import require_admin
from app.db import models
from app.db.session import get_db


router = APIRouter()


@router.get("/message-validation/summary")
def message_validation_summary(
    campaign_key: str = Query(default=CAMPAIGN_KEY, max_length=120),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    rows = (
        db.query(models.MessageTestParticipant)
        .filter(models.MessageTestParticipant.campaign_key == campaign_key)
        .order_by(models.MessageTestParticipant.assigned_at.asc())
        .all()
    )
    variants = {
        variant: summarize_rows([row for row in rows if row.variant == variant])
        for variant in ("A", "B")
    }
    return {
        "campaign_key": campaign_key,
        "coding_version": "ko-v1",
        "variants": variants,
        "decision": _decision(variants),
    }


def _decision(variants: dict) -> str:
    passed = [variant for variant, data in variants.items() if data["passed_gate"]]
    if len(passed) == 2:
        return "advance_both"
    if len(passed) == 1:
        return f"advance_{passed[0].lower()}"
    if all(data["enough_sample"] for data in variants.values()):
        return "rewrite_and_retest"
    return "collect_more"
