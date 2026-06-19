"""인증 엔드포인트 앱 레벨 레이트리밋 검증.

conftest 가 전역적으로 limiter 를 끄므로, 이 테스트에서만 잠시 켜서 429 를 확인한다.
"""
import pytest

from app.core.rate_limit import limiter


@pytest.fixture
def rate_limited():
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.enabled = False
    limiter.reset()


def test_login_rate_limited(client, rate_limited):
    """로그인 10/분 초과 시 429."""
    body = {"username": "nobody@example.com", "password": "wrongpass123"}
    statuses = []
    for _ in range(13):
        r = client.post("/api/v1/auth/login", data=body)
        statuses.append(r.status_code)
    # 처음 10회는 401(자격 실패), 이후 429 가 나타나야 함
    assert 429 in statuses
    assert statuses.count(401) <= 10
