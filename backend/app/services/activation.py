"""활성화 계측 — 프로필 완성·첫 안전 판정 타임스탬프 기록.

판정과 기록을 이 모듈 한 곳에 둔다. 호출처가 여럿(users.py PUT /me · auth.py register ·
bids.py /calculate·/calculate/detailed · ai.py analysis)이라 판정 로직이 엔드포인트마다
복사되면 서로 갈라진다.
"""
from datetime import datetime, timezone

from app.core.analytics import log_event
from app.core.logging import get_logger

logger = get_logger(__name__)


def is_profile_complete(user) -> bool:
    """활성화 1단계(프로필 완성) 판정 — 면허·소재지가 모두 채워졌는가.

    auth.py 의 needs_profile(둘 다 비었을 때만 True)과는 방향이 다르다: 저쪽은
    "온보딩 안내가 필요한가", 여기는 "자격 판정이 가능한 상태인가"를 묻는다.
    """
    licenses = (getattr(user, "licenses", None) or "").strip()
    location = (getattr(user, "location", None) or "").strip()
    return bool(licenses and location)


def record_profile_completed(user) -> None:
    """프로필 완성 1회 기록. 커밋은 호출자 트랜잭션에 편승한다.

    이미 기록된 뒤(profile_completed_at is not None)에는 프로필을 비워도 되돌리지
    않는다. best-effort — 실패해도 예외를 전파하지 않는다.
    """
    try:
        if user.profile_completed_at is None and is_profile_complete(user):
            user.profile_completed_at = datetime.now(timezone.utc)
            log_event("profile_complete", user_id=user.id)
    except Exception as e:
        logger.warning(f"activation profile_complete hook 실패(non-fatal): {e}")


def record_first_activation(db, user, source: str) -> None:
    """첫 "안전 판정" 1회 기록. best-effort — 실패해도 예외를 전파하지 않는다.

    자체 commit 하므로 반드시 본 기능이 **성공한 뒤**(응답 직전), 세션에 다른
    pending 변경이 없는 시점에 부를 것 — 검증·레이트리밋 앞에서 커밋하면 실패한
    요청까지 "활성화"로 남고, pending 이 섞이면 rollback 이 그것까지 지운다.
    """
    try:
        if user is None or user.first_activation_at is not None:
            return
        user.first_activation_at = datetime.now(timezone.utc)
        db.add(user)
        db.commit()
        log_event("activation_first_safe_check", user_id=user.id, source=source)
    except Exception as e:
        logger.warning(f"activation first_activation_at hook 실패(non-fatal): {e}")
        try:
            db.rollback()
        except Exception:
            logger.warning("activation hook rollback 도 실패 — 무시(best-effort)")
