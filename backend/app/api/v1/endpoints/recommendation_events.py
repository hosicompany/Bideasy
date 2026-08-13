"""Authenticated user-decision events linked to a recommendation id."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db import models
from app.db.session import get_db
from app.schemas.algorithm_evidence import UserDecisionCreate, UserDecisionResponse
from app.services.algorithm_evidence import record_user_decision


router = APIRouter()


@router.post(
    "/{recommendation_id}/decisions",
    response_model=UserDecisionResponse,
    status_code=201,
)
def create_user_decision(
    recommendation_id: str,
    payload: UserDecisionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    try:
        row, duplicate = record_user_decision(
            db,
            recommendation_id=recommendation_id,
            user_id=current_user.id,
            event=payload,
        )
        db.commit()
        db.refresh(row)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return UserDecisionResponse(
        id=row.id,
        recommendation_id=row.recommendation_id,
        event_type=row.event_type,
        occurred_at=row.occurred_at,
        duplicate=duplicate,
    )
