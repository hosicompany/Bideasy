"""자가보정(autocalibrate) 공개 지표 엔드포인트.

랜딩(index.html)·대시보드의 자가보정 섹션이 사용. **인증 불필요(공개 마케팅 지표).**
프론트는 응답 실패/필드 누락 시 빌드 내장 기본값으로 graceful fallback 하므로,
이 엔드포인트는 "있으면 라이브, 없으면 정적" 성격이다.

데이터 출처:
- passRate/dropRate/weekly: 자가보정 전략 저장소(FileStrategyStore)의 active·이력 버전
  metrics(pass_rate). 주간 recalibrate(월 04:00 KST)가 갱신.
- dataCount: 정적 개찰 베이스(4,848) + 누적 OpeningResult.
- lastTrainedAt: active 버전 생성시각. nextUpdateDays: 다음 월요일 04:00 까지.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db import models
from app.core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)

# 정적 개찰 데이터 베이스(opening_results_*.json). 누적 DB 와 합산해 표기.
_STATIC_BASE = 4848
_KST = timezone(timedelta(hours=9))


@router.get("/stats")
def get_autocalibrate_stats(db: Session = Depends(get_db)):
    """자가보정 공개 지표. 인증 불필요."""
    out = {
        "passRate": 94.9,
        "dropRate": 5.1,
        "dataCount": _STATIC_BASE,
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
        if metrics.get("pass_rate") is not None:
            out["passRate"] = round(float(metrics["pass_rate"]), 1)
            out["dropRate"] = round(100.0 - out["passRate"], 1)
        if active.created_at:
            try:
                out["lastTrainedAt"] = datetime.fromisoformat(active.created_at).strftime("%Y-%m-%d %H:%M KST")
            except Exception:
                out["lastTrainedAt"] = active.created_at
        # 주간 추이: 채택된 버전들의 pass_rate (시간순, 최근 12)
        try:
            vers = [v for v in store.list_versions() if (v.metrics or {}).get("pass_rate") is not None]
            vers.sort(key=lambda v: v.created_at or "")
            weekly = [round(float(v.metrics["pass_rate"]), 1) for v in vers][-12:]
            if len(weekly) >= 3:
                out["weekly"] = weekly
        except Exception:
            pass
    except Exception as e:
        logger.info(f"autocalibrate stats: strategy store unavailable ({e}) — 기본값 사용")

    # ── 누적 개찰 데이터 건수 ──
    try:
        out["dataCount"] = _STATIC_BASE + db.query(models.OpeningResult).count()
    except Exception:
        pass

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
