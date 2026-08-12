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
    "opening_stats.rebuild": "누적 개찰 통계 재집계",
    "trial.send_expiry_reminders": "체험 만료 알림",
    "deadline.send_reminders": "마감 리마인더",
    "recommend.send_matches": "맞춤 추천 알림",
    "billing.charge_due_subscriptions": "자동결제 갱신",
    "admin_report.send_daily": "일일 리포트",
}

#: `days_back` 인자를 **실제로 받는** 태스크와 그 상한. 안 받는 태스크에 넘기면
#: 워커에서 TypeError 로 죽는다. 상한이 태스크마다 다른 이유:
#: - 개찰 크롤은 창 하나당 API 호출이 수백 회라 30일이면 5,000회를 넘고, 그중
#:   한 창만 실패해도 그 런의 참가자 저장이 통째로 폐기된다.
#: - 예측 검증은 API 호출이 0 이고 DB 만 조회한다. 스케줄 기본값이 30 이므로
#:   상한을 7 로 씌우면 **자기 기본값조차 수동으로 못 넣는다**.
_DAYS_BACK_TASKS = {
    "verification.daily_crawl_opening_results": 7,
    "verification.daily_verify_predictions": 90,
}


@router.get("/system/triggers")
def list_triggers(_admin=Depends(require_admin)):
    """수동 실행 가능한 작업 목록."""
    return {"tasks": [{"name": k, "desc": v} for k, v in _TRIGGERABLE.items()]}


@router.post("/system/tasks/{task_name}/trigger")
def trigger_task(task_name: str, days_back: int | None = None,
                 _admin=Depends(require_admin)):
    """허용된 Celery task 수동 실행 → task_id 반환.

    `days_back` 은 조회 창을 넓혀 **누락을 보충**하는 용도다. 정기 크롤 창(2일)
    밖에서 개찰이 확정된 건을 뒤늦게 줍는다.

    ⚠️ **과대 반영은 이 경로로 복구되지 않는다.** 참가자 저장은 병합이라 값이
    단조 증가하므로, 창을 넓혀 여러 번 불러도 부푼 참여사수는 내려가지 않는다.
    그 경우는 운영 DB 에서 직접 정리해야 한다.
    """
    if task_name not in _TRIGGERABLE:
        raise HTTPException(status_code=400, detail="허용되지 않은 작업입니다.")
    if days_back is not None:
        # 이 인자를 받지 않는 태스크에 넘기면 워커에서 TypeError 로 죽는다.
        if task_name not in _DAYS_BACK_TASKS:
            raise HTTPException(status_code=400,
                                detail="이 작업은 days_back 을 받지 않습니다.")
        # 하한이 1인 이유: 0 이면 길이 0 짜리 창이 되어 API 0건 → 아무 일도
        # 안 일어났는데 "성공"으로 보고된다.
        limit = _DAYS_BACK_TASKS[task_name]
        if not 1 <= days_back <= limit:
            raise HTTPException(
                status_code=400,
                detail=f"days_back 은 1~{limit} 이어야 합니다.")
    kwargs = {"days_back": days_back} if days_back is not None else {}
    task = celery_app.send_task(task_name, kwargs=kwargs)
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
