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
        "app.tasks.admin_report_tasks",
        "app.tasks.billing_tasks",
        "app.tasks.notice_crawl_tasks",
        "app.tasks.deadline_tasks",
        "app.tasks.recommendation_tasks",
        "app.tasks.content_tasks",
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
    "daily-admin-report": {
        "task": "admin_report.send_daily",
        "schedule": crontab(hour=9, minute=0),
    },
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
    # 5) 매일 03:00 — 만료 임박 자동결제 구독 갱신 청구
    "daily-billing-renewal": {
        "task": "billing.charge_due_subscriptions",
        "schedule": crontab(hour=3, minute=0),
    },
    # 6) 매일 06:00 — 공사/용역/물품 신규 공고 크롤 → 누적 DB 적재 (검색 재현율)
    "daily-notice-crawl": {
        "task": "notices.crawl_daily",
        "schedule": crontab(hour=6, minute=0),
    },
    # 7) 매월 1일 05:00 — 마감 90일 경과 공고 정리 (참조분 보존)
    "monthly-notice-purge": {
        "task": "notices.purge_old",
        "schedule": crontab(hour=5, minute=0, day_of_month=1),
    },
    # 8) 매일 07:00 — 자격 맞춤 추천 (신규 공고 ↔ 프로필 매칭)
    "daily-recommendations": {
        "task": "recommend.send_matches",
        "schedule": crontab(hour=7, minute=0),
    },
    # 9) 매일 10:30 — 추적 공고 마감 리마인더 (D-3/D-1/당일)
    "daily-deadline-reminders": {
        "task": "deadline.send_reminders",
        "schedule": crontab(hour=10, minute=30),
    },
    # 10) 매일 06:30 — A값 Tier 2 백필 (첨부 파싱)
    "daily-avalue-backfill": {
        "task": "notices.backfill_avalue",
        "schedule": crontab(hour=6, minute=30),
    },
    # 11) 매주 월요일 08:00 — Track B 데이터스토리 주간 초안 생성(유예 publish_at 부여)
    "weekly-data-story-draft": {
        "task": "content.weekly_data_story",
        "schedule": crontab(hour=8, minute=0, day_of_week=1),
    },
    # 12) 매시 05분 — 예약/유예 자동발행(publish_at 도래한 draft 발행)
    "publish-scheduled-posts": {
        "task": "content.publish_scheduled",
        "schedule": crontab(minute=5),
    },
}
