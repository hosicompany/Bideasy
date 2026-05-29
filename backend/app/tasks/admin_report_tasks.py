"""
운영자 일일 리포트 Celery 태스크

매일 09:00 KST 실행:
1. admin_daily_report.collect_daily_report() 로 어제 지표 수집
2. is_admin 사용자에게 Notification 적재
3. SLACK_WEBHOOK_URL 환경변수 있으면 슬랙으로도 발송
4. (선택) ADMIN_REPORT_EMAIL 환경변수 있으면 SMTP 발송 — 인프라 추가 시
"""
from __future__ import annotations

import json
import urllib.request

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.logging import get_logger
from app.db import models
from app.db.session import SessionLocal
from app.services.admin_daily_report import (
    collect_daily_report,
    format_report_as_markdown,
)

logger = get_logger(__name__)


def _post_slack(webhook_url: str, text: str) -> bool:
    """슬랙 incoming webhook 발송. 실패 시 False (조용히 — 운영 멈춤 방지)."""
    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps({"text": text}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        logger.warning(f"Slack webhook failed: {e}")
        return False


@celery_app.task(name="admin_report.send_daily")
def send_daily_admin_report() -> dict:
    """
    매일 09:00 KST 자동 실행.

    1) 어제 지표 수집
    2) is_admin=True 사용자에게 Notification 적재 (in-app 알림)
    3) SLACK_WEBHOOK_URL 환경변수 있으면 슬랙 발송
    """
    db = SessionLocal()
    try:
        report = collect_daily_report(db)
        markdown = format_report_as_markdown(report)

        # ─── 1. Notification 적재 (admin 사용자 전원) ─────────
        admin_users = db.query(models.User).filter(models.User.is_admin == True).all()  # noqa: E712
        noti_count = 0
        for admin in admin_users:
            noti = models.Notification(
                user_id=admin.id,
                title=f"📊 일일 리포트 — {report['target_date']}",
                body=report["summary_line"],
                noti_type="ADMIN_DAILY_REPORT",
                data_json={"report": report},
                is_read=0,
            )
            db.add(noti)
            noti_count += 1
        db.commit()

        # ─── 2. 슬랙 발송 (환경변수 있을 때만) ───────────────
        slack_url = getattr(settings, "SLACK_WEBHOOK_URL", None) or ""
        slack_ok = False
        if slack_url:
            slack_ok = _post_slack(slack_url, markdown)

        logger.info(
            f"[admin_report.send_daily] notifications={noti_count}, "
            f"slack={'ok' if slack_ok else ('skipped' if not slack_url else 'failed')}"
        )
        return {
            "ok": True,
            "target_date": report["target_date"],
            "notifications_created": noti_count,
            "slack_sent": slack_ok,
            "anomalies": len(report["anomalies"]),
        }
    except Exception as e:
        db.rollback()
        logger.error(f"[admin_report.send_daily] error: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}
    finally:
        db.close()
