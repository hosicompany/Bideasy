"""리드 육성 발송 태스크 — 진단 이후 새로 올라온 조건 부합 공고 알림.

퍼널상 위치(docs/LEAD_ACQUISITION.md §3): 진단 → 캡처 → **육성** → 가입.
캡처 직후 웰컴 1통은 엔드포인트가 즉시 보내고(`endpoints/leads.py`), 그 뒤의 주기
접촉이 여기다.

발송 빈도를 주 1회로 잡은 이유
------------------------------
반송률 5%·불만율 0.1% 를 넘으면 AWS 가 계정 발송을 정지시키고, 그러면 광고뿐 아니라
**거래 메일까지 함께 막힌다.** 리드 모수가 아직 작은 지금은 빈도를 올려 얻을 것보다
잃을 것이 크다. 빈도는 나중에 올리기 쉽지만, 스팸으로 인식된 신뢰는 되돌리기 어렵다.

발송 판정은 스스로 하지 않는다
------------------------------
동의·철회·2년 재확인은 `consent.sendable_filter` 가, 억제 목록·멱등·원장은
`nurture.send_marketing` 이 책임진다. 이 태스크가 `marketing_consent == True` 를
직접 보고 판단하면 철회·만료가 누락돼 위법 발송이 된다.
"""
from datetime import datetime, timedelta

from app.core.celery_app import celery_app
from app.core.logging import get_logger
from app.db import models
from app.db.session import SessionLocal
from app.services import consent as consent_service
from app.services import lead_matching, nurture

logger = get_logger(__name__)

# 이 기간 안에 올라온 공고를 "새 공고"로 본다. 주 1회 발송이므로 한 주치를 덮는다.
NEW_WINDOW_DAYS = 7

# 메일 본문에 나열할 공고 수 — 전부 넣으면 읽히지 않는다. 나머지는 웹에서 본다.
_LIST_N = 5

# 한 회차에 처리할 리드 상한(폭주 방어). 넘으면 다음 회차로 넘어간다.
_MAX_LEADS_PER_RUN = 2000


def _period_key(now: datetime) -> str:
    """멱등 키의 주기 구간 — ISO 주차. 같은 주에는 두 번 나가지 않는다."""
    iso = now.isocalendar()
    return f"{iso[0]}W{iso[1]:02d}"


def _notice_brief(n: models.Notice) -> dict:
    return {
        "title": n.title or "",
        "organization": n.organization or "",
        "end_date_label": n.end_date.strftime("%m/%d") if n.end_date else "",
    }


@celery_app.task(name="nurture.send_lead_matches")
def send_lead_matches() -> dict:
    """동의한 리드에게 조건에 맞는 신규 공고를 주 1회 알린다."""
    db = SessionLocal()
    results = {"leads_checked": 0, "sent": 0, "skipped_no_match": 0, "blocked": 0}
    try:
        now = datetime.now()
        since = now - timedelta(days=NEW_WINDOW_DAYS)
        period = _period_key(now)

        leads = (
            db.query(models.Lead)
            .filter(consent_service.sendable_filter(models.Lead))
            .filter(models.Lead.email.isnot(None))
            .filter(models.Lead.email != "")
            # 가입 전환된 리드는 회원 대상 알림이 따로 나간다 — 같은 사람에게 두 번 보내지 않는다.
            .filter(models.Lead.nurture_status != "converted")
            .limit(_MAX_LEADS_PER_RUN)
            .all()
        )

        for lead in leads:
            results["leads_checked"] += 1
            matched = lead_matching.match_notices(
                db, lead.industry, lead.licenses, lead.region, since=since
            )
            if not matched:
                results["skipped_no_match"] += 1
                continue

            row = nurture.send_marketing(
                db, lead,
                subject_type="lead",
                template="lead_new_matches",
                ctx={
                    "region": lead.region,
                    "industry": lead.industry,
                    "new_count": len(matched),
                    "notices": [_notice_brief(n) for n in matched[:_LIST_N]],
                },
                dedupe_key=f"lead_new_matches:lead:{lead.id}:{period}",
            )
            if row.status in ("sent", "dry_run"):
                results["sent"] += 1
                if lead.nurture_status != "converted":
                    lead.nurture_status = "sent"
            else:
                # skipped(동의 철회·억제·중복) 또는 failed — 원장에 사유가 남아 있다.
                results["blocked"] += 1

        db.commit()
        logger.info(f"[nurture.send_lead_matches] {results}")
        return results
    except Exception as e:
        db.rollback()
        logger.error(f"[nurture.send_lead_matches] error: {e}", exc_info=True)
        return {"error": str(e), **results}
    finally:
        db.close()
