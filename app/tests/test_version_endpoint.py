from fastapi.testclient import TestClient
from app.newsroom.main import app, SITE_NAME, SITE_TAGLINE

client = TestClient(app)

def test_version_endpoint():
    response = client.get("/version")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    data = response.json()
    assert data["name"] == SITE_NAME
    assert data["tagline"] == SITE_TAGLINE
