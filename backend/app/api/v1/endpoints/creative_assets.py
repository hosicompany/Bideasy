"""Public delivery gate for approved creative derivatives."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services import creative_asset_delivery as delivery


router = APIRouter()


@router.api_route(
    "/assets/generated/{storage_path:path}",
    methods=["GET", "HEAD"],
    include_in_schema=False,
)
def get_published_creative_asset(
    storage_path: str,
    db: Session = Depends(get_db),
):
    try:
        output = delivery.public_output_by_path(db, storage_path)
        return delivery.accelerated_response(output, public=True)
    except delivery.CreativeAssetNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "자산을 찾을 수 없어요") from exc
