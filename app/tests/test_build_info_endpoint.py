from fastapi.testclient import TestClient

from newsroom.main import app


def test_get_build_info_endpoint():
    client = TestClient(app)
    response = client.get("/build-info")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    data = response.json()
    assert data["service"] == "newsroom"
    assert data["status"] == "ok"
