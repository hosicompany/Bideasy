"""Authenticated user-decision events linked to a recommendation id."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
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
    except IntegrityError as exc:
        # 같은 idempotency_key 의 동시 요청: 둘 다 `.first()` 를 통과한 뒤 진 쪽이 유니크
        # 인덱스에서 죽는다. 500 이 아니라 문서대로 idempotent duplicate 로 돌려준다
        # (growth.py 의 유니크 경합 처리와 같은 관례). 진짜 다른 사유의 무결성 위반이면
        # 기존 행이 없으므로 그대로 올린다.
        db.rollback()
        existing = (
            db.query(models.UserDecisionEvent)
            .filter(models.UserDecisionEvent.idempotency_key == payload.idempotency_key)
            .first()
        )
        if existing is None:
            raise
        # 서비스(record_user_decision)의 duplicate 계약과 동일해야 한다 — 소유자가 다르거나
        # **다른 recommendation** 에 같은 키를 재사용한 경우는 duplicate 가 아니라 403 이다.
        # 경합 경로만 이 검사를 빼면 순차 요청은 403, 동시 요청은 201 로 갈린다(#128 리뷰).
        if existing.user_id != current_user.id or existing.recommendation_id != recommendation_id:
            raise HTTPException(status_code=403, detail="idempotency key belongs to a different recommendation") from exc
        row, duplicate = existing, True

    return UserDecisionResponse(
        id=row.id,
        recommendation_id=row.recommendation_id,
        event_type=row.event_type,
        occurred_at=row.occurred_at,
        duplicate=duplicate,
    )
