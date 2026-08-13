"""자가보정(autocalibrate) 공개 지표 엔드포인트.

랜딩(index.html)·대시보드의 자가보정 섹션이 사용. **인증 불필요(공개 마케팅 지표).**
검증된 실측이 없으면 숫자를 만들지 않고 ``null``과 상태를 반환한다.

데이터 출처:
- passRate/dropRate/weekly: 자가보정 전략 저장소(FileStrategyStore)의 active·이력 버전
  metrics(pass_rate). 주간 recalibrate(월 04:00 KST)가 갱신.
- dataCount: 현재 품질 계약을 통과한 distinct notice 수.
- lastTrainedAt: active 버전 생성시각. nextUpdateDays: 다음 월요일 04:00 까지.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)

_KST = timezone(timedelta(hours=9))


def _has_verified_active_lineage(version) -> bool:
    """Legacy/locally written metrics are not public performance evidence."""
    return bool(
        version.status in {"active", "archived"}
        and version.candidate_id
        and version.gate_decision_id
        and version.approval_id
        and version.data_manifest_hash
        and version.code_sha
        and version.route
    )


@router.get("/stats")
def get_autocalibrate_stats(db: Session = Depends(get_db)):
    """자가보정 공개 지표. 인증 불필요."""
    out = {
        "passRate": None,
        "dropRate": None,
        "dataCount": 0,
        "evidenceStatus": "NOT_VERIFIED",
        "exclusions": {},
        "weekly": None,
        "lastTrainedAt": None,
        "nextUpdateDays": 2,
    }

    # ── 전략 저장소: 통과율 + 학습시각 + 주간 추이 ──
    try:
        from app.services.autocalibrate.strategy_store import get_default_store
        store = get_default_store()
        active = store.load_active()
        metrics = active.metrics or {}
        if _has_verified_active_lineage(active) and metrics.get("pass_rate") is not None:
            out["passRate"] = round(float(metrics["pass_rate"]), 1)
            out["dropRate"] = round(100.0 - out["passRate"], 1)
            out["evidenceStatus"] = "ACTIVE_STRATEGY_METRIC"
        if active.created_at:
            try:
                out["lastTrainedAt"] = datetime.fromisoformat(active.created_at).strftime("%Y-%m-%d %H:%M KST")
            except Exception:
                out["lastTrainedAt"] = active.created_at
        # 주간 추이: 사용자에게 실제 적용됐던 버전만. 후보/거부본을 섞으면
        # 아직 배포하지 않은 성능이 제품 실적처럼 보인다.
        try:
            vers = [
                v
                for v in store.list_versions()
                if _has_verified_active_lineage(v)
                and (v.metrics or {}).get("pass_rate") is not None
            ]
            vers.sort(key=lambda v: v.created_at or "")
            weekly = [round(float(v.metrics["pass_rate"]), 1) for v in vers][-12:]
            if len(weekly) >= 3:
                out["weekly"] = weekly
        except Exception:
            pass
    except Exception as e:
        logger.info(f"autocalibrate stats: strategy store unavailable ({e})")

    # ── 동일 품질 계약을 통과한 distinct notice 수 ──
    try:
        from app.services.autocalibrate.dataset import DatasetQualityStats, load_records

        quality = DatasetQualityStats()
        records = load_records(
            db=db,
            strict_db=True,
            quality_stats=quality,
            enforce_base_consistency=True,
            require_a_value_status=True,
            require_observation_time=True,
            require_feature_lineage=True,
        )
        out["dataCount"] = len({record.bid_no for record in records})
        out["exclusions"] = quality.as_dict()
    except Exception as e:
        logger.info(f"autocalibrate stats: verified dataset unavailable ({e})")

    # ── 다음 자동 갱신까지 (월요일 04:00 KST) ──
    try:
        now = datetime.now(_KST)
        days = (0 - now.weekday()) % 7  # Monday=0
        if days == 0 and now.hour >= 4:
            days = 7
        out["nextUpdateDays"] = days if days > 0 else 7
    except Exception:
        pass

    return out
