"""Service-token protected API used by the authenticated operator-Mac runner."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.creative_runner_auth import require_creative_runner
from app.db.session import get_db
from app.schemas.creative import (
    RunnerClaimOut,
    RunnerClaimRequest,
    RunnerFailOut,
    RunnerFailRequest,
    RunnerHeartbeatOut,
    RunnerHeartbeatRequest,
    RunnerOutputResponse,
)
from app.services import creative_asset_delivery as delivery
from app.services import creative_input_assets as input_assets
from app.services import creative_workflow as workflow


router = APIRouter(dependencies=[Depends(require_creative_runner)])


def _raise_api_error(exc: workflow.CreativeWorkflowError) -> None:
    if isinstance(exc, workflow.CreativeNotFound):
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if isinstance(exc, workflow.CreativeValidationError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.get("/outputs/{output_id}/download")
def download_creative_output_for_runner(
    output_id: int,
    db: Session = Depends(get_db),
):
    """Let the authenticated local runner reuse a pre-approval output."""
    try:
        return delivery.accelerated_response(delivery.output_by_id(db, output_id), public=False)
    except delivery.CreativeAssetNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "자산을 찾을 수 없어요") from exc


@router.get("/inputs/{asset_id}/download")
def download_creative_input_for_runner(
    asset_id: int,
    db: Session = Depends(get_db),
):
    """Download a private input using only the rotating runner service token."""
    try:
        return input_assets.private_response(input_assets.asset_by_id(db, asset_id))
    except input_assets.CreativeInputAssetNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "입력 자산을 찾을 수 없어요") from exc


@router.post(
    "/claim",
    response_model=RunnerClaimOut,
    responses={status.HTTP_204_NO_CONTENT: {"description": "대기 작업 없음"}},
)
def claim_creative_job(
    payload: RunnerClaimRequest,
    db: Session = Depends(get_db),
):
    try:
        claim = workflow.claim_attempt(
            db,
            runner_id=payload.runner_id,
            cli_version=payload.cli_version,
        )
    except workflow.CreativeWorkflowError as exc:
        _raise_api_error(exc)
    if claim is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return claim


@router.post("/{attempt_id}/heartbeat", response_model=RunnerHeartbeatOut)
def heartbeat_creative_job(
    attempt_id: int,
    payload: RunnerHeartbeatRequest,
    db: Session = Depends(get_db),
):
    try:
        attempt = workflow.heartbeat(
            db,
            attempt_id,
            runner_id=payload.runner_id,
            status=payload.status,
            higgsfield_job_id=payload.higgsfield_job_id,
            virality_job_id=payload.virality_job_id,
        )
    except workflow.CreativeWorkflowError as exc:
        _raise_api_error(exc)
    return {
        "attempt_id": attempt.id,
        "status": attempt.status,
        "lease_expires_at": attempt.lease_expires_at,
    }


@router.post("/{attempt_id}/output", response_model=RunnerOutputResponse)
async def upload_creative_output(
    attempt_id: int,
    file: UploadFile = File(...),
    runner_id: str = Form(..., min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.:-]+$"),
    kind: str = Form(...),
    is_primary: bool = Form(False),
    metadata_json: str = Form("{}", max_length=65_536),
    sha256: str | None = Form(default=None, max_length=64),
    db: Session = Depends(get_db),
):
    try:
        metadata: Any = json.loads(metadata_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "metadata_json이 올바른 JSON이 아니에요",
        ) from exc
    if not isinstance(metadata, dict):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "metadata_json은 JSON object여야 해요",
        )
    try:
        output = await workflow.store_output(
            db,
            attempt_id,
            upload=file,
            runner_id=runner_id,
            kind=kind,
            is_primary=is_primary,
            metadata=metadata,
            expected_sha256=sha256,
        )
    except workflow.CreativeWorkflowError as exc:
        _raise_api_error(exc)
    return {
        "output": output,
        "attempt_status": output.attempt.status,
        "creative_status": output.attempt.brief.status,
    }


@router.post("/{attempt_id}/fail", response_model=RunnerFailOut)
def fail_creative_job(
    attempt_id: int,
    payload: RunnerFailRequest,
    db: Session = Depends(get_db),
):
    try:
        attempt = workflow.fail_attempt(
            db,
            attempt_id,
            runner_id=payload.runner_id,
            error=payload.error,
            auth_required=payload.auth_required,
            retryable=payload.retryable,
        )
    except workflow.CreativeWorkflowError as exc:
        _raise_api_error(exc)
    return {"attempt_id": attempt.id, "status": attempt.status}
