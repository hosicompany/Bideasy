def test_register_and_login(client):
    # Register returns user info (not token)
    resp = client.post("/api/v1/auth/register", json={
        "email": "test@example.com",
        "password": "test1234",
        "company_name": "TestCo",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "test@example.com"
    assert data["company_name"] == "TestCo"

    # Login returns JWT token
    resp = client.post("/api/v1/auth/login", data={
        "username": "test@example.com",
        "password": "test1234",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_wrong_password(client):
    # Register first
    client.post("/api/v1/auth/register", json={
        "email": "wrong@example.com",
        "password": "correct",
        "company_name": "Co",
    })
    # Login with wrong password
    resp = client.post("/api/v1/auth/login", data={
        "username": "wrong@example.com",
        "password": "incorrect",
    })
    assert resp.status_code == 401
