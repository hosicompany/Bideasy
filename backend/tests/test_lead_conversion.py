"""
리드 → 가입 전환 링크 + 어드민 리드 대시보드 테스트 (2026-07-18)
=================================================================
승리 이론("안전에 지갑을 낸다") 측정 고리의 회귀 보호.

세션 스코프 파일 DB라 커밋이 테스트 간 누적된다 → 각 테스트는 leads 를 비우고
유니크 이메일을 써서 다른 파일의 User/Lead 오염과 독립적으로 동작한다.
"""
import uuid
from datetime import datetime, timedelta

from app.db import models
from app.services.lead_conversion import link_leads_to_user, normalize_email


def _clear_leads(db):
    db.query(models.Lead).delete()
    db.commit()


def _uniq(tag):
    return f"{tag}-{uuid.uuid4().hex[:10]}@test.com"


def _mk_lead(db, email, industry="전기공사", region="부산광역시", status="new", days_ago=0):
    lead = models.Lead(
        email=email,
        industry=industry,
        region=region,
        matched_count=3,
        nurture_status=status,
        source="web_diagnose",
        created_at=datetime.utcnow() - timedelta(days=days_ago),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


class TestNormalizeEmail:
    def test_lower_and_trim(self):
        assert normalize_email("  Foo@Bar.COM ") == "foo@bar.com"

    def test_empty(self):
        assert normalize_email("") is None
        assert normalize_email(None) is None
        assert normalize_email("   ") is None


class TestLinkOnSignup:
    def test_email_signup_links_lead(self, client, db_session):
        _clear_leads(db_session)
        email = _uniq("convert")
        _mk_lead(db_session, email)
        res = client.post("/api/v1/auth/register", json={
            "email": email, "password": "pw12345678",
        })
        assert res.status_code == 200
        user_id = res.json()["id"]
        lead = db_session.query(models.Lead).filter(models.Lead.email == email).first()
        db_session.refresh(lead)
        assert lead.converted_user_id == user_id
        assert lead.nurture_status == "converted"

    def test_email_normalized_match(self, client, db_session):
        """리드는 대문자·공백 이메일, 가입은 소문자 — 정규화로 매칭돼야 한다."""
        _clear_leads(db_session)
        token = uuid.uuid4().hex[:10]
        lead_email = f"  Mixed{token}@Test.com "
        signup_email = f"mixed{token}@test.com"
        _mk_lead(db_session, lead_email)
        res = client.post("/api/v1/auth/register", json={
            "email": signup_email, "password": "pw12345678",
        })
        assert res.status_code == 200
        lead = db_session.query(models.Lead).first()
        db_session.refresh(lead)
        assert lead.converted_user_id == res.json()["id"]

    def test_multiple_leads_same_email_all_linked(self, client, db_session):
        """capture dedup 없음 → 동일 이메일 다건 전부 전환."""
        _clear_leads(db_session)
        email = _uniq("multi")
        _mk_lead(db_session, email, region="부산광역시")
        _mk_lead(db_session, email, region="서울특별시")
        res = client.post("/api/v1/auth/register", json={
            "email": email, "password": "pw12345678",
        })
        assert res.status_code == 200
        leads = db_session.query(models.Lead).filter(models.Lead.email == email).all()
        assert len(leads) == 2
        for lead in leads:
            db_session.refresh(lead)
            assert lead.nurture_status == "converted"
            assert lead.converted_user_id == res.json()["id"]

    def test_no_matching_lead_is_noop(self, client, db_session):
        """진단 안 한 사람의 가입은 아무 리드도 안 건드린다."""
        _clear_leads(db_session)
        lead_email = _uniq("someone")
        _mk_lead(db_session, lead_email)
        res = client.post("/api/v1/auth/register", json={
            "email": _uniq("different"), "password": "pw12345678",
        })
        assert res.status_code == 200
        lead = db_session.query(models.Lead).filter(models.Lead.email == lead_email).first()
        db_session.refresh(lead)
        assert lead.converted_user_id is None
        assert lead.nurture_status == "new"

    def test_signup_succeeds_even_if_linking_would_fail(self, client, db_session, monkeypatch):
        """리드 링크가 터져도 가입은 성공해야 한다(best-effort 백스톱)."""
        import app.api.v1.endpoints.auth as auth_mod

        def boom(db, user):
            raise RuntimeError("linking exploded")

        monkeypatch.setattr(auth_mod, "link_leads_to_user", boom)
        res = client.post("/api/v1/auth/register", json={
            "email": _uniq("resilient"), "password": "pw12345678",
        })
        assert res.status_code == 200  # 가입은 성공


class TestLinkService:
    def test_only_unconverted_updated(self, db_session):
        """이미 다른 유저로 전환된 리드는 덮어쓰지 않는다."""
        _clear_leads(db_session)
        email = _uniq("taken")
        lead = _mk_lead(db_session, email)
        lead.converted_user_id = 999
        lead.nurture_status = "converted"
        db_session.commit()

        user = models.User(email=_uniq("newuser"), hashed_password="x", tier="free")
        # 링크 대상은 lead.email 과 같아야 하므로 user.email 을 맞춘다
        user.email = email
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        n = link_leads_to_user(db_session, user)
        assert n == 0
        db_session.refresh(lead)
        assert lead.converted_user_id == 999  # 안 바뀜


class TestAdminLeadDashboard:
    def test_stats_counts_and_conversion(self, admin_client, db_session):
        _clear_leads(db_session)
        _mk_lead(db_session, _uniq("d1"), industry="전기공사")
        converted = _mk_lead(db_session, _uniq("d2"), industry="전기공사")
        converted.converted_user_id = 42
        converted.nurture_status = "converted"
        db_session.commit()

        res = admin_client.get("/api/v1/admin/leads/stats")
        assert res.status_code == 200
        data = res.json()
        assert data["total_leads"] == 2
        assert data["converted_leads"] == 1
        assert data["conversion_pct"] == 50.0
        industries = {row["industry"] for row in data["by_industry"]}
        assert "전기공사" in industries
        assert isinstance(data["daily"], list)
        assert len(data["recent"]) == 2

    def test_requires_admin(self, client, pro_client):
        assert client.get("/api/v1/admin/leads/stats").status_code in (401, 403)
        assert pro_client.get("/api/v1/admin/leads/stats").status_code == 403
