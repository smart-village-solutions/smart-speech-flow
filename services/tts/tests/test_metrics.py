def test_metrics(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "# HELP" in response.text
