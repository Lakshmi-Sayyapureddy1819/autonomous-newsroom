from fastapi.testclient import TestClient

from newsroom.main import app


def test_get_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    data = response.json()
    assert data["status"] == "ok"
