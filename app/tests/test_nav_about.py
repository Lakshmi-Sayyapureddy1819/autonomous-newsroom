from fastapi.testclient import TestClient

from newsroom.db import init_db
from newsroom.main import app


def test_about_link_in_navigation():
    init_db()  # Ensure database is initialized for the test
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "<a href=\"/version\">About</a>" in response.text
