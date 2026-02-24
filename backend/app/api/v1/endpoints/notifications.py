from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.security import get_current_user
from app.db import models
from app.db.session import get_db

logger = get_logger(__name__)
router = APIRouter()


# --- Schemas ---

class RegisterDeviceRequest(BaseModel):
    fcm_token: str
    device_type: str  # android | ios | web


class NotificationOut(BaseModel):
    id: int
    title: str
    body: str
    noti_type: str
    data_json: dict | None = None
    is_read: bool
    created_at: str


# --- Endpoints ---

@router.post("/register-device", status_code=status.HTTP_204_NO_CONTENT)
def register_device(
    req: RegisterDeviceRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Register or update an FCM device token for the current user."""
    if req.device_type not in ("android", "ios", "web"):
        raise HTTPException(status_code=400, detail="device_type must be android, ios, or web")

    existing = (
        db.query(models.DeviceToken)
        .filter(
            models.DeviceToken.user_id == current_user.id,
            models.DeviceToken.fcm_token == req.fcm_token,
        )
        .first()
    )

    if existing:
        existing.device_type = req.device_type
        existing.updated_at = datetime.now(timezone.utc)
    else:
        token = models.DeviceToken(
            user_id=current_user.id,
            fcm_token=req.fcm_token,
            device_type=req.device_type,
        )
        db.add(token)

    db.commit()
    logger.info(f"device_token_registered: user_id={current_user.id}, device_type={req.device_type}")


@router.delete("/unregister-device", status_code=status.HTTP_204_NO_CONTENT)
def unregister_device(
    req: RegisterDeviceRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Remove an FCM device token (e.g. on logout)."""
    db.query(models.DeviceToken).filter(
        models.DeviceToken.user_id == current_user.id,
        models.DeviceToken.fcm_token == req.fcm_token,
    ).delete()
    db.commit()


@router.get("/list")
def list_notifications(
    unread_only: bool = False,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """List notifications for the current user."""
    query = db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id,
    )
    if unread_only:
        query = query.filter(models.Notification.is_read == 0)

    notifications = query.order_by(models.Notification.created_at.desc()).limit(limit).all()

    return [
        NotificationOut(
            id=n.id,
            title=n.title,
            body=n.body,
            noti_type=n.noti_type,
            data_json=n.data_json,
            is_read=bool(n.is_read),
            created_at=n.created_at.isoformat() if n.created_at else "",
        )
        for n in notifications
    ]


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_as_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Mark a single notification as read."""
    noti = db.query(models.Notification).filter(
        models.Notification.id == notification_id,
        models.Notification.user_id == current_user.id,
    ).first()
    if not noti:
        raise HTTPException(status_code=404, detail="알림을 찾을 수 없어요.")
    noti.is_read = 1
    db.commit()


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_as_read(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Mark all notifications as read for the current user."""
    db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id,
        models.Notification.is_read == 0,
    ).update({"is_read": 1})
    db.commit()


@router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Get count of unread notifications."""
    count = db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id,
        models.Notification.is_read == 0,
    ).count()
    return {"count": count}
