from celery import Celery
from celery.schedules import crontab
from app.core.config import settings

celery_app = Celery(
    "bideasy",
    broker=settings.celery_broker,
    backend=settings.celery_backend,
    include=["app.tasks.calibration_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Seoul",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# 정기 자가보정 스케줄 — 매주 월요일 새벽 4시 (개찰 데이터가 주중 누적된 후)
# should_recalibrate() 가드로 새 데이터 없으면 즉시 스킵하므로 비용 없음.
celery_app.conf.beat_schedule = {
    "weekly-strategy-recalibration": {
        "task": "autocalibrate.recalibrate_strategy",
        "schedule": crontab(hour=4, minute=0, day_of_week=1),
    },
}
