"""Admin creative brief lifecycle and Higgsfield queue operations."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.core.security import require_admin
from app.db import models
from app.db.session import get_db
from app.schemas.creative import (
    CreativeApproveRequest,
    CreativeAttemptOut,
    CreativeBriefCreate,
    CreativeBriefOut,
    CreativeBriefUpdate,
    CreativeChangesRequest,
    CreativeInputAssetUploadOut,
    CreativePublishedRequest,
)
from app.services import creative_asset_delivery as delivery
from app.services import creative_input_assets as input_assets
from app.services import creative_workflow as workflow


router = APIRouter()


def _raise_api_error(exc: workflow.CreativeWorkflowError) -> None:
    if isinstance(exc, workflow.CreativeNotFound):
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if isinstance(exc, workflow.CreativeValidationError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.get("/creative-outputs/{output_id}/download")
def download_creative_output_for_review(
    output_id: int,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_admin),
):
    """Preview any stored output after explicit admin authentication."""
    try:
        return delivery.accelerated_response(delivery.output_by_id(db, output_id), public=False)
    except delivery.CreativeAssetNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "자산을 찾을 수 없어요") from exc


@router.get("/creative-inputs/{asset_id}/download")
def download_creative_input_for_review(
    asset_id: int,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_admin),
):
    """Preview a private generation input after explicit admin authentication."""
    try:
        return input_assets.private_response(input_assets.asset_by_id(db, asset_id))
    except input_assets.CreativeInputAssetNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "입력 자산을 찾을 수 없어요") from exc


@router.get("/creatives", response_model=list[CreativeBriefOut])
def list_creatives(
    creative_status: str | None = Query(default=None, alias="status"),
    source_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_admin),
):
    try:
        return workflow.list_briefs(
            db,
            status=creative_status,
            source_type=source_type,
            limit=limit,
        )
    except workflow.CreativeWorkflowError as exc:
        _raise_api_error(exc)


@router.post(
    "/creatives/from-blog/{post_id}",
    response_model=CreativeBriefOut,
    status_code=status.HTTP_201_CREATED,
)
def create_creative_from_blog(
    post_id: int,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_admin),
):
    try:
        return workflow.create_brief_from_blog(db, post_id)
    except workflow.CreativeWorkflowError as exc:
        _raise_api_error(exc)


@router.post(
    "/creatives",
    response_model=CreativeBriefOut,
    status_code=status.HTTP_201_CREATED,
)
def create_creative(
    payload: CreativeBriefCreate,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_admin),
):
    return workflow.create_brief(db, payload)


@router.get("/creatives/{creative_id}", response_model=CreativeBriefOut)
def get_creative(
    creative_id: str,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_admin),
):
    try:
        return workflow.get_brief(db, creative_id)
    except workflow.CreativeWorkflowError as exc:
        _raise_api_error(exc)


@router.post(
    "/creatives/{creative_id}/inputs",
    response_model=CreativeInputAssetUploadOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_creative_input(
    creative_id: str,
    file: UploadFile = File(...),
    role: str = Form(..., min_length=1, max_length=30),
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    """Store a source UI/storyboard/voice/reference without changing workflow state."""
    try:
        asset = await input_assets.store_input_asset(
            db,
            creative_id,
            upload=file,
            role=role,
            created_by=admin.id,
        )
    except input_assets.CreativeInputAssetNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except input_assets.CreativeInputAssetValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return input_assets.upload_response(asset)


@router.get(
    "/creatives/{creative_id}/inputs",
    response_model=list[CreativeInputAssetUploadOut],
)
def list_creative_inputs(
    creative_id: str,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_admin),
):
    """List recoverable private inputs even when a manifest edit was not saved."""
    try:
        return [
            input_assets.upload_response(asset)
            for asset in input_assets.list_assets(db, creative_id)
        ]
    except input_assets.CreativeInputAssetNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.put("/creatives/{creative_id}", response_model=CreativeBriefOut)
def update_creative(
    creative_id: str,
    payload: CreativeBriefUpdate,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_admin),
):
    try:
        return workflow.update_brief(db, creative_id, payload)
    except workflow.CreativeWorkflowError as exc:
        _raise_api_error(exc)


@router.post("/creatives/{creative_id}/queue", response_model=CreativeAttemptOut)
def queue_creative(
    creative_id: str,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_admin),
):
    try:
        return workflow.queue_brief(db, creative_id)
    except workflow.CreativeWorkflowError as exc:
        _raise_api_error(exc)


@router.post("/creatives/{creative_id}/approve", response_model=CreativeBriefOut)
def approve_creative(
    creative_id: str,
    payload: CreativeApproveRequest | None = None,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    payload = payload or CreativeApproveRequest()
    try:
        return workflow.approve_brief(
            db,
            creative_id,
            admin_user_id=admin.id,
            note=payload.note,
            review_json=payload.review_json,
            override_reason=payload.override_reason,
        )
    except workflow.CreativeWorkflowError as exc:
        _raise_api_error(exc)


@router.post("/creatives/{creative_id}/request-changes", response_model=CreativeBriefOut)
def request_creative_changes(
    creative_id: str,
    payload: CreativeChangesRequest,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_admin),
):
    try:
        return workflow.request_changes(
            db,
            creative_id,
            reason=payload.reason,
            review_json=payload.review_json,
        )
    except workflow.CreativeWorkflowError as exc:
        _raise_api_error(exc)


@router.post("/creatives/{creative_id}/mark-published", response_model=CreativeBriefOut)
def mark_creative_published(
    creative_id: str,
    payload: CreativePublishedRequest | None = None,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_admin),
):
    try:
        return workflow.mark_published(
            db,
            creative_id,
            published_at=payload.published_at if payload else None,
        )
    except workflow.CreativeWorkflowError as exc:
        _raise_api_error(exc)
