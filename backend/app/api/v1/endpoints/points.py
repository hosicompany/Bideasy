from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.db import models
from app.schemas import point as point_schemas
from app.core.security import get_current_user

router = APIRouter()


@router.get("/balance", response_model=point_schemas.PointBalance)
def get_balance(current_user: models.User = Depends(get_current_user)):
    """포인트 잔액 조회"""
    return point_schemas.PointBalance(
        points=current_user.points,
        formatted=f"{current_user.points:,}원",
    )


@router.post("/deduct", response_model=point_schemas.PointDeductResponse)
def deduct_points(
    request: point_schemas.PointDeductRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """투찰금액 복사 시 포인트 차감 (건당 500원)"""
    cost = point_schemas.BID_COPY_COST

    if current_user.points < cost:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"포인트가 부족합니다. 현재 {current_user.points:,}원, 필요 {cost:,}원",
        )

    # 차감
    current_user.points -= cost
    balance_after = current_user.points

    # 거래 기록
    tx = models.PointTransaction(
        user_id=current_user.id,
        amount=-cost,
        balance_after=balance_after,
        tx_type="BID_COPY",
        description=f"투찰금액 복사 ({request.bid_no})",
        bid_no=request.bid_no,
    )
    db.add(tx)
    db.commit()

    return point_schemas.PointDeductResponse(
        success=True,
        remaining_points=balance_after,
        cost=cost,
        message=f"투찰금액 복사 완료. {cost:,}원 차감됨.",
    )


@router.post("/charge", response_model=point_schemas.PointChargeResponse)
def charge_points(
    request: point_schemas.PointChargeRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """포인트 충전 (추후 결제 연동)"""
    if request.amount <= 0:
        raise HTTPException(status_code=400, detail="충전 금액은 0보다 커야 합니다.")

    current_user.points += request.amount
    balance_after = current_user.points

    tx = models.PointTransaction(
        user_id=current_user.id,
        amount=request.amount,
        balance_after=balance_after,
        tx_type="CHARGE",
        description=f"포인트 충전 {request.amount:,}원",
    )
    db.add(tx)
    db.commit()

    return point_schemas.PointChargeResponse(
        success=True,
        charged_amount=request.amount,
        remaining_points=balance_after,
        message=f"{request.amount:,}원 충전 완료.",
    )


@router.get("/history", response_model=List[point_schemas.PointTransaction])
def get_point_history(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """포인트 거래 이력 조회"""
    transactions = (
        db.query(models.PointTransaction)
        .filter(models.PointTransaction.user_id == current_user.id)
        .order_by(models.PointTransaction.created_at.desc())
        .limit(limit)
        .all()
    )
    return transactions
