from fastapi.testclient import TestClient

from newsroom.main import app


def test_get_agent_demo_endpoint():
    client = TestClient(app)
    response = client.get("/agent-demo")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "service": "autonomous-newsroom",
        "status": "ok",
    }
