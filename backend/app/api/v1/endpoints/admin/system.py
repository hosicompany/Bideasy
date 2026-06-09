"""관리자 — 시스템 운영: 수동 Celery 트리거 + 작업 상태 폴링 (Phase D)."""
from fastapi import APIRouter, Depends, HTTPException

from celery.result import AsyncResult

from app.core.security import require_admin
from app.core.celery_app import celery_app
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()

# 수동 트리거 허용 task 화이트리스트 (이름 → 설명)
_TRIGGERABLE = {
    "notices.crawl_daily": "공고 크롤 (공사/용역/물품 신규)",
    "notices.backfill_avalue": "A값 첨부 백필",
    "notices.purge_old": "오래된 공고 정리",
    "verification.daily_crawl_opening_results": "개찰결과 크롤",
    "verification.daily_verify_predictions": "예측 검증",
    "trial.send_expiry_reminders": "체험 만료 알림",
    "deadline.send_reminders": "마감 리마인더",
    "recommend.send_matches": "맞춤 추천 알림",
    "billing.charge_due_subscriptions": "자동결제 갱신",
    "admin_report.send_daily": "일일 리포트",
}


@router.get("/system/triggers")
def list_triggers(_admin=Depends(require_admin)):
    """수동 실행 가능한 작업 목록."""
    return {"tasks": [{"name": k, "desc": v} for k, v in _TRIGGERABLE.items()]}


@router.post("/system/tasks/{task_name}/trigger")
def trigger_task(task_name: str, _admin=Depends(require_admin)):
    """허용된 Celery task 수동 실행 → task_id 반환."""
    if task_name not in _TRIGGERABLE:
        raise HTTPException(status_code=400, detail="허용되지 않은 작업입니다.")
    task = celery_app.send_task(task_name)
    logger.info(f"manual task dispatched: {task_name} ({task.id})")
    return {"task_id": task.id, "task_name": task_name, "status": "dispatched"}


@router.get("/system/tasks/{task_id}")
def task_status(task_id: str, _admin=Depends(require_admin)):
    """Celery 작업 상태/결과 폴링."""
    res = AsyncResult(task_id, app=celery_app)
    out = {"task_id": task_id, "state": res.state}
    try:
        if res.successful():
            out["result"] = res.result
        elif res.failed():
            out["error"] = str(res.result)
    except Exception as e:
        out["error"] = f"결과 조회 오류: {e}"
    return out
