from fastapi.testclient import TestClient

from newsroom.db import init_db
from newsroom.main import app


def test_about_link_in_navigation():
    init_db()  # Ensure database is initialized for the test
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "<a href=\"/version\">About</a>" in response.text

def test_about_page_content():
    client = TestClient(app)
    response = client.get("/version")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    data = response.json()
    assert "name" in data
    assert "tagline" in data
