from fastapi.testclient import TestClient

from newsroom.main import app


def test_runs_heading():
    client = TestClient(app)
    response = client.get("/runs")
    assert response.status_code == 200
    assert "<h1>Pipeline run log</h1>" in response.text
