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
import hashlib
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

# 한 회차에 처리할 리드 상한(폭주 방어). id 오름차순으로 자르므로 뒤쪽 리드는
# 이번 회차에서 빠진다 — 상한에 걸리면 로그로 남겨 조용한 누락이 되지 않게 한다.
_MAX_LEADS_PER_RUN = 2000


def _period_key(now: datetime) -> str:
    """멱등 키의 주기 구간 — ISO 주차. 같은 주에는 두 번 나가지 않는다."""
    iso = now.isocalendar()
    return f"{iso[0]}W{iso[1]:02d}"


def _recipient_key(email: str) -> str:
    """멱등 키의 주체 = 수신자. 같은 사람이 재진단해 Lead 행이 늘어도 한 통만 나간다."""
    return hashlib.sha1((email or "").strip().lower().encode("utf-8")).hexdigest()[:16]


def _notice_brief(n: models.Notice) -> dict:
    return {
        "title": n.title or "",
        "organization": n.organization or "",
        "end_date_label": n.end_date.strftime("%m/%d") if n.end_date else "",
        # 메일에서 공고 상세(/bid/{no})로 바로 보내기 위한 키. 없으면 템플릿이
        # 링크 없이 제목만 렌더한다(깨진 링크를 만들지 않는다).
        "bid_no": n.bid_no or "",
    }


@celery_app.task(name="nurture.send_lead_matches")
def send_lead_matches() -> dict:
    """동의한 리드에게 조건에 맞는 신규 공고를 주 1회 알린다."""
    db = SessionLocal()
    results = {"leads_checked": 0, "sent": 0, "skipped_no_match": 0, "blocked": 0, "errors": 0}
    try:
        now = datetime.now()
        window_start = now - timedelta(days=NEW_WINDOW_DAYS)
        period = _period_key(now)

        leads = (
            db.query(models.Lead)
            .filter(consent_service.sendable_filter(models.Lead))
            .filter(models.Lead.email.isnot(None))
            .filter(models.Lead.email != "")
            # 가입 전환된 리드는 회원 대상 알림이 따로 나간다 — 같은 사람에게 두 번 보내지 않는다.
            .filter(models.Lead.nurture_status != "converted")
            .order_by(models.Lead.id)     # 상한에 걸릴 때 잘리는 지점을 결정적으로
            .limit(_MAX_LEADS_PER_RUN)
            .all()
        )
        if len(leads) == _MAX_LEADS_PER_RUN:
            logger.warning(
                "[nurture.send_lead_matches] 회차 상한 %s 도달 — id 오름차순 이후 리드는 "
                "이번 회차에서 제외됐다(조용한 누락 방지 로그)", _MAX_LEADS_PER_RUN,
            )

        # 같은 사람이 재진단하면 Lead 행이 여러 개 생긴다. 발송은 수신자 단위여야 하므로
        # 이메일당 가장 최근 행 하나만 남긴다(멱등 키도 수신자 기준이라 이중 방어).
        by_recipient: dict[str, models.Lead] = {}
        for lead in leads:
            key = _recipient_key(lead.email)
            prev = by_recipient.get(key)
            if prev is None or (lead.id or 0) > (prev.id or 0):
                by_recipient[key] = lead

        # (공종 루트, 지역) 이 같으면 매칭 결과도 같다 — 리드마다 500행을 다시 판정하지
        # 않도록 회차 안에서 재사용한다(리드가 늘수록 이게 비용의 전부가 된다).
        match_cache: dict[tuple, list] = {}

        for lead in by_recipient.values():
            results["leads_checked"] += 1
            try:
                # 갓 캡처된 리드에게는 웰컴이 이미 같은 공고를 보여줬다. 리드 생성 이후
                # 올라온 것만 "새 공고"로 본다 — 첫 주부터 중복을 보내면 스팸으로 읽힌다.
                since = window_start
                if lead.created_at and lead.created_at > since:
                    since = lead.created_at

                cache_key = (
                    lead_matching.detect_root(lead.industry, lead.licenses),
                    (lead.region or ""),
                    since.replace(microsecond=0),
                )
                matched = match_cache.get(cache_key)
                if matched is None:
                    matched = lead_matching.match_notices(
                        db, lead.industry, lead.licenses, lead.region, since=since
                    )
                    match_cache[cache_key] = matched

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
                        "capped": len(matched) >= lead_matching.MATCH_LIMIT,
                        "notices": [_notice_brief(n) for n in matched[:_LIST_N]],
                    },
                    dedupe_key=f"lead_new_matches:email:{_recipient_key(lead.email)}:{period}",
                )
                if row.status in ("sent", "dry_run"):
                    results["sent"] += 1
                    if lead.nurture_status != "converted":
                        lead.nurture_status = "sent"
                else:
                    # skipped(동의 철회·억제·중복) 또는 failed — 원장에 사유가 남아 있다.
                    results["blocked"] += 1
            except Exception as e:  # noqa: BLE001 — 리드 1건의 실패가 배치를 죽이지 않는다
                # 이게 없으면 데이터 결함 1건이 매주 같은 지점에서 배치를 끊어 나머지
                # 전원이 조용히 메일을 못 받는다(beat 는 실패를 알리지 않는다).
                results["errors"] += 1
                db.rollback()
                logger.warning(f"[nurture.send_lead_matches] lead={lead.id} 실패(건너뜀): {e}")

        db.commit()
        logger.info(f"[nurture.send_lead_matches] {results}")
        return results
    except Exception as e:
        db.rollback()
        logger.error(f"[nurture.send_lead_matches] error: {e}", exc_info=True)
        return {"error": str(e), **results}
    finally:
        db.close()
