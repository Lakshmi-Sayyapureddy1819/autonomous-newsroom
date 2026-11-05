from fastapi.testclient import TestClient

from newsroom.main import SITE_NAME, SITE_TAGLINE, app


def test_get_version_endpoint():
    client = TestClient(app)
    response = client.get("/version")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    data = response.json()
    assert data["name"] == SITE_NAME
    assert data["tagline"] == SITE_TAGLINE
