"""관리자 — 자가보정(투찰 전략 자동보정) 운영 (Phase D).

기존 strategy_store + calibration_tasks 를 노출만 한다.
- 버전 목록/상세, 수동 재보정 실행(Celery), 롤백.
- 현재 active·이력은 /admin/stats/autocalibrate-status (dashboard) 재사용.
"""
from fastapi import APIRouter, Depends, HTTPException

from app.core.security import require_admin
from app.core.celery_app import celery_app
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


def _store():
    from app.services.autocalibrate.strategy_store import get_default_store
    return get_default_store()


@router.get("/autocalibrate/versions")
def list_versions(_admin=Depends(require_admin)):
    """전략 버전 전체 목록 (최신순)."""
    try:
        versions = _store().list_versions()
    except Exception as e:
        logger.warning(f"autocalibrate versions load failed: {e}")
        return {"items": [], "total": 0, "error": str(e)}
    items = [
        {
            "version_id": v.version_id,
            "created_at": v.created_at,
            "status": v.status,
            "parent_version": v.parent_version,
            "metrics": v.metrics,
            "notes": v.notes,
        }
        for v in versions
    ]
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {"items": items, "total": len(items)}


@router.get("/autocalibrate/versions/{version_id}")
def get_version(version_id: str, _admin=Depends(require_admin)):
    """전략 버전 상세 (params 포함)."""
    v = _store().get(version_id)
    if not v:
        raise HTTPException(status_code=404, detail="버전을 찾을 수 없습니다.")
    return v.to_dict()


@router.post("/autocalibrate/run")
def run_recalibrate(_admin=Depends(require_admin)):
    """수동 자가보정 1 사이클 실행 (Celery 비동기 — 수십 초 소요 가능).

    task_id 반환 → /admin/system/tasks/{task_id} 로 진행 폴링.
    """
    task = celery_app.send_task("autocalibrate.recalibrate_strategy")
    logger.info(f"manual autocalibrate dispatched: {task.id}")
    return {"task_id": task.id, "status": "dispatched"}


@router.post("/autocalibrate/rollback/{version_id}")
def rollback_version(version_id: str, _admin=Depends(require_admin)):
    """과거 버전으로 롤백 (active 교체) + 계산기 캐시 재로드."""
    store = _store()
    if not store.get(version_id):
        raise HTTPException(status_code=404, detail="버전을 찾을 수 없습니다.")
    restored = store.rollback(version_id)
    try:
        from app.services.calculator import reload_strategy_cache
        reload_strategy_cache()
    except Exception as e:
        logger.warning(f"reload_strategy_cache failed after rollback: {e}")
    logger.info(f"autocalibrate rollback → {restored.version_id}")
    return {"rolled_back_to": version_id, "active_version": restored.version_id}
