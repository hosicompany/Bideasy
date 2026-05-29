"""
관리자 대시보드 통계 엔드포인트 테스트.
"""
from datetime import datetime, timedelta, timezone

from app.db import models


def _insert_payment(db, user_id, amount, status="CONFIRMED", confirmed_at=None, refunded_at=None, order_id="SUB_X"):
    p = models.PaymentOrder(
        user_id=user_id,
        order_id=order_id,
        amount=amount,
        status=status,
        method="카드",
        confirmed_at=confirmed_at,
        refunded_at=refunded_at,
    )
    db.add(p)
    db.commit()
    return p


# ── /stats/revenue ─────────────────────────────────────────
# 주의: 테스트가 같은 DB 를 공유하므로 절대값 대신 baseline 대비 delta 로 검증

def test_revenue_stats_structure(admin_client):
    """응답 구조 검증."""
    resp = admin_client.get("/api/v1/admin/stats/revenue?days=30")
    assert resp.status_code == 200
    data = resp.json()
    assert "today" in data and "revenue" in data["today"]
    assert "this_month" in data
    assert "mrr" in data
    assert len(data["series"]) == 30


def test_revenue_stats_today_delta(admin_client, db_session):
    """오늘 결제 추가 → today.revenue delta 증가."""
    base = admin_client.get("/api/v1/admin/stats/revenue?days=7").json()
    user = db_session.query(models.User).filter_by(email="test-admin@test.com").first()
    now = datetime.now(timezone.utc)
    _insert_payment(db_session, user.id, 14900, confirmed_at=now, order_id="SUB_DELTA_1")
    _insert_payment(db_session, user.id, 140000, confirmed_at=now, order_id="SUB_DELTA_2")

    after = admin_client.get("/api/v1/admin/stats/revenue?days=7").json()
    assert after["today"]["revenue"] - base["today"]["revenue"] == 14900 + 140000
    assert after["today"]["orders"] - base["today"]["orders"] == 2


def test_revenue_excludes_refunded(admin_client, db_session):
    """환불된 주문은 매출에 포함 안 됨."""
    base = admin_client.get("/api/v1/admin/stats/revenue?days=7").json()
    user = db_session.query(models.User).filter_by(email="test-admin@test.com").first()
    now = datetime.now(timezone.utc)
    _insert_payment(
        db_session, user.id, 99900, confirmed_at=now, refunded_at=now,
        order_id="SUB_REFUNDED_1",
    )

    after = admin_client.get("/api/v1/admin/stats/revenue?days=7").json()
    assert after["today"]["revenue"] == base["today"]["revenue"]  # 변화 없음


def test_revenue_mrr_counts_active_pro(admin_client, db_session):
    db_session.add(models.User(
        email="mrr-pro@test.com", hashed_password="x", tier="pro",
        subscription_expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    ))
    db_session.add(models.User(
        email="mrr-pro-plus@test.com", hashed_password="x", tier="pro_plus",
        subscription_expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    ))
    db_session.commit()

    resp = admin_client.get("/api/v1/admin/stats/revenue")
    data = resp.json()
    assert data["mrr"] >= 14900 + 29900  # 최소한 위 두 명


# ── /stats/users ───────────────────────────────────────────

def test_user_stats_basic(admin_client, db_session):
    # admin 본인 + 추가 3명
    db_session.add(models.User(email="us1@test.com", hashed_password="x", tier="free"))
    db_session.add(models.User(email="us2@test.com", hashed_password="x", tier="pro"))
    db_session.add(models.User(
        email="us3@test.com", hashed_password="x", tier="free",
        trial_started_at=datetime.now(timezone.utc),
        trial_expires_at=datetime.now(timezone.utc) + timedelta(days=14),
    ))
    db_session.commit()

    resp = admin_client.get("/api/v1/admin/stats/users?days=7")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 4
    assert data["by_tier"]["free"] >= 2
    assert data["by_tier"]["pro"] >= 1
    assert data["by_status"]["trial_active"] >= 1
    assert len(data["signups_series"]) == 7


def test_user_stats_trial_conversion(admin_client, db_session):
    """trial_started + pro = converted."""
    db_session.add(models.User(
        email="conv1@test.com", hashed_password="x", tier="pro",
        trial_started_at=datetime.now(timezone.utc) - timedelta(days=20),
        trial_expires_at=datetime.now(timezone.utc) - timedelta(days=6),
        subscription_expires_at=datetime.now(timezone.utc) + timedelta(days=24),
    ))
    db_session.add(models.User(
        email="conv2@test.com", hashed_password="x", tier="free",
        trial_started_at=datetime.now(timezone.utc) - timedelta(days=20),
        trial_expires_at=datetime.now(timezone.utc) - timedelta(days=6),
    ))
    db_session.commit()

    resp = admin_client.get("/api/v1/admin/stats/users")
    data = resp.json()
    assert data["trial_conversion"]["trial_started_count"] >= 2
    assert data["trial_conversion"]["converted_to_paid"] >= 1
    assert 0 <= data["trial_conversion"]["rate"] <= 1


# ── /stats/ai-cost ─────────────────────────────────────────

def test_ai_cost_empty(admin_client):
    resp = admin_client.get("/api/v1/admin/stats/ai-cost?days=7")
    assert resp.status_code == 200
    data = resp.json()
    assert data["today"]["calls"] == 0
    assert data["today"]["tokens"] == 0
    assert len(data["series"]) == 7


def test_ai_cost_with_data(admin_client, db_session):
    notice = models.Notice(
        bid_no="AI-COST-TEST", title="Test", basic_price=100_000_000,
        contract_type="CONSTRUCTION",
    )
    db_session.add(notice)
    db_session.commit()
    log = models.AIAnalysisLog(
        bid_no=notice.bid_no, llm_model="gpt-4o-mini", token_usage=1500,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(log)
    db_session.commit()

    resp = admin_client.get("/api/v1/admin/stats/ai-cost?days=7")
    data = resp.json()
    assert data["today"]["calls"] >= 1
    assert data["today"]["tokens"] >= 1500
    assert data["today"]["estimated_usd"] > 0
    assert "gpt-4o-mini" in data["by_model"]


# ── /stats/system-health ───────────────────────────────────

def test_system_health(admin_client):
    """DB 는 항상 ok, Redis/Celery 는 환경에 따라 ok/false 둘 다 가능."""
    resp = admin_client.get("/api/v1/admin/stats/system-health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["db"]["ok"] is True
    assert "redis" in data
    assert "celery" in data
    assert data["pending_payments_24h"] >= 0


def test_system_health_pending_payments(admin_client, db_session):
    user = db_session.query(models.User).filter_by(email="test-admin@test.com").first()
    # 25시간 전 PENDING
    old_pending = models.PaymentOrder(
        user_id=user.id, order_id="OLD_PENDING_1", amount=5000, status="PENDING",
        created_at=datetime.now(timezone.utc) - timedelta(hours=25),
    )
    db_session.add(old_pending)
    db_session.commit()

    resp = admin_client.get("/api/v1/admin/stats/system-health")
    assert resp.json()["pending_payments_24h"] >= 1


# ── /stats/autocalibrate-status ────────────────────────────

def test_autocalibrate_status(admin_client):
    """active.json + history.jsonl 파싱 — 실제 운영 데이터로 검증."""
    resp = admin_client.get("/api/v1/admin/stats/autocalibrate-status")
    assert resp.status_code == 200
    data = resp.json()
    # active 있을 수도, 없을 수도. next_scheduled 는 항상 있어야
    assert "next_scheduled" in data
    assert data["next_scheduled"]
    assert isinstance(data["recent_history"], list)
