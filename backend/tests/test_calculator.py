def test_calculate(client):
    resp = client.post("/api/v1/bids/calculate", json={
        "basic_price": 100000000,
        "a_value": 0,
        "rate": -2.0,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "result_price" in data
    assert "is_safe" in data
