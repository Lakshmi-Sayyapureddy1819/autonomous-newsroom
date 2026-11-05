import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from newsroom.main import app

EXPECTED = {"service": "autonomous-newsroom", "status": "ok"}
EXPECTED_BODY = '{"service":"autonomous-newsroom","status":"ok"}'


def assert_build_info(client: TestClient) -> None:
    """The contract from Issue #48: the exact JSON, not merely HTTP 200."""
    response = client.get("/build-info")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == EXPECTED
    assert response.text == EXPECTED_BODY


def test_build_info_returns_the_exact_json():
    assert_build_info(TestClient(app))


@pytest.mark.parametrize(
    "wrong",
    [
        {"service": "newsroom", "status": "ok"},  # the value PR #49 shipped
        {"service": "autonomous-newsroom", "status": "up"},
        {"service": "autonomous-newsroom"},
        {"service": "autonomous-newsroom", "status": "ok", "extra": 1},
    ],
)
def test_the_contract_check_rejects_incorrect_values(wrong):
    """The check itself must fail for a wrong payload (guards against echoing the code)."""
    bad = FastAPI()

    @bad.get("/build-info")
    def build_info() -> dict:
        return wrong

    with pytest.raises(AssertionError):
        assert_build_info(TestClient(bad))
