"""
관리자 권한 가드 테스트
========================
- require_admin 의존성: 익명/비-admin/admin 3 케이스
- 모든 /admin/* 라우트가 가드를 거치는지 자동 회귀 (가드 누락 방지)

admin_client fixture 는 conftest.py 에서 제공.
"""
from app.core.security import require_admin


# ── require_admin 의존성 3 케이스 ────────────────────────────

def test_admin_endpoint_rejects_anonymous(client):
    """Authorization 헤더 없음 → 401."""
    resp = client.get("/api/v1/admin/accuracy")
    assert resp.status_code == 401


def test_admin_endpoint_rejects_non_admin(free_client):
    """is_admin=False 사용자 → 403."""
    resp = free_client.get("/api/v1/admin/accuracy")
    assert resp.status_code == 403
    assert "관리자" in resp.json()["detail"]


def test_admin_endpoint_rejects_pro_plus_non_admin(pro_plus_client):
    """Pro+ 구독자도 is_admin=False 면 403 (기존 동작 변경 — tier 가 아닌 is_admin 기준)."""
    resp = pro_plus_client.get("/api/v1/admin/accuracy")
    assert resp.status_code == 403


def test_admin_endpoint_accepts_admin(admin_client):
    """is_admin=True 사용자 → 200."""
    resp = admin_client.get("/api/v1/admin/accuracy")
    assert resp.status_code == 200
    data = resp.json()
    assert "generated_at" in data
    assert "db" in data


def test_admin_recent_accepts_admin(admin_client):
    resp = admin_client.get("/api/v1/admin/accuracy/recent?limit=5")
    assert resp.status_code == 200
    assert "items" in resp.json()


def test_admin_opening_results_accepts_admin(admin_client):
    resp = admin_client.get("/api/v1/admin/opening-results/recent?limit=5")
    assert resp.status_code == 200


# ── 모든 /admin/* 라우트가 require_admin 거치는지 자동 회귀 ────────

def _flatten_dependencies(dependant, seen=None) -> set:
    """FastAPI Dependant 의 모든 의존 함수를 재귀적으로 수집."""
    if seen is None:
        seen = set()
    if not dependant:
        return seen
    if getattr(dependant, "call", None) is not None:
        seen.add(dependant.call)
    for sub in getattr(dependant, "dependencies", []) or []:
        _flatten_dependencies(sub, seen)
    return seen


def test_all_admin_routes_have_guard():
    """모든 /api/v1/admin/* 라우트가 require_admin 의존성을 거치는지 자동 검증.

    엔드포인트 추가 시 _admin=Depends(require_admin) 누락 회귀 방지.
    라우터 수준 dependency 도 검사 대상.
    """
    from main import app

    admin_routes = [
        r for r in app.routes
        if getattr(r, "path", "").startswith("/api/v1/admin")
    ]
    assert admin_routes, "admin 라우트가 하나도 등록되지 않았습니다 — 라우터 마운트 확인"

    missing = []
    for route in admin_routes:
        dependant = getattr(route, "dependant", None)
        deps = _flatten_dependencies(dependant)
        if require_admin not in deps:
            missing.append(route.path)

    assert not missing, (
        "다음 admin 라우트에 require_admin 가드 누락:\n"
        + "\n".join(f"  - {p}" for p in missing)
    )
