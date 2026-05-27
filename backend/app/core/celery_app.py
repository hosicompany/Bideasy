from celery import Celery
from celery.schedules import crontab
from app.core.config import settings

celery_app = Celery(
    "bideasy",
    broker=settings.celery_broker,
    backend=settings.celery_backend,
    include=[
        "app.tasks.calibration_tasks",
        "app.tasks.verification_tasks",
        "app.tasks.trial_tasks",
    ],
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

# 정기 스케줄 — Asia/Seoul 기준
# 1) 매일 10:00 — 14일 Pro 체험 만료 알림 (D-3, D-1, 만료후 1일 win-back)
# 2) 매일 19:00 — 어제 개찰결과 크롤 → opening_results 적재
# 3) 매일 20:00 — notices ↔ opening_results 비교 → predictions_log.jsonl 누적
# 4) 매주 월요일 04:00 — 누적된 predictions_log 와 historical 데이터로 자가보정 1 사이클
celery_app.conf.beat_schedule = {
    "daily-trial-expiry-reminders": {
        "task": "trial.send_expiry_reminders",
        "schedule": crontab(hour=10, minute=0),
    },
    "daily-crawl-opening-results": {
        "task": "verification.daily_crawl_opening_results",
        "schedule": crontab(hour=19, minute=0),
        "kwargs": {"days_back": 2},
    },
    "daily-verify-predictions": {
        "task": "verification.daily_verify_predictions",
        "schedule": crontab(hour=20, minute=0),
        "kwargs": {"days_back": 30, "limit": 500},
    },
    "weekly-strategy-recalibration": {
        "task": "autocalibrate.recalibrate_strategy",
        "schedule": crontab(hour=4, minute=0, day_of_week=1),
    },
}
