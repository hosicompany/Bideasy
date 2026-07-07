"""Tests for user profile endpoints."""


class TestGetProfile:
    """GET /api/v1/users/me"""

    def test_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        resp = client.get("/api/v1/users/me")
        assert resp.status_code == 401

    def test_get_profile(self, free_client):
        """Returns current user profile."""
        resp = free_client.get("/api/v1/users/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "test-free@test.com"
        assert "points" in data
        assert "tier" in data

    def test_get_profile_pro(self, pro_client):
        """Pro user profile shows pro tier."""
        resp = pro_client.get("/api/v1/users/me")
        assert resp.status_code == 200
        assert resp.json()["tier"] == "pro"


class TestUpdateProfile:
    """PUT /api/v1/users/me"""

    def test_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        resp = client.put("/api/v1/users/me", json={"company_name": "test"})
        assert resp.status_code == 401

    def test_update_company_name(self, free_client):
        """Update company name succeeds."""
        resp = free_client.put(
            "/api/v1/users/me",
            json={"company_name": "테스트건설"},
        )
        assert resp.status_code == 200
        assert resp.json()["company_name"] == "테스트건설"

    def test_update_multiple_fields(self, free_client):
        """Update multiple profile fields."""
        resp = free_client.put(
            "/api/v1/users/me",
            json={
                "company_name": "BidEasy건설",
                "ceo_name": "홍길동",
                "licenses": "건축공사업",
                "location": "서울특별시",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["company_name"] == "BidEasy건설"
        assert data["ceo_name"] == "홍길동"
        assert data["licenses"] == "건축공사업"
        assert data["location"] == "서울특별시"

    def test_partial_update(self, free_client):
        """Partial update only changes specified fields."""
        # Set initial
        free_client.put(
            "/api/v1/users/me",
            json={"company_name": "원래이름", "ceo_name": "원래대표"},
        )
        # Update only company_name
        resp = free_client.put(
            "/api/v1/users/me",
            json={"company_name": "변경이름"},
        )
        assert resp.status_code == 200
        assert resp.json()["company_name"] == "변경이름"
        # ceo_name should remain
        assert resp.json()["ceo_name"] == "원래대표"
