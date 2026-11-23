import pytest
from fastapi.testclient import TestClient

from agent.model_clients.stub import StubModelClient, demo_rules
from agent.orchestrator import Agent
from api.main import MAX_ROWS_IN_RESPONSE, create_app


@pytest.fixture
def make_client(db):
    def _make(api_key=None, model=None):
        agent = Agent(db, model or StubModelClient(rules=demo_rules()))
        return TestClient(create_app(agent=agent, api_key=api_key))

    return _make


def test_health_ok_for_stub(make_client):
    with make_client() as c:
        r = c.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


class EndpointDown(StubModelClient):
    def health(self):
        return {"status": "Creating"}


def test_health_stays_ok_when_endpoint_is_down(make_client):
    with make_client(model=EndpointDown()) as c:
        r = c.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_ready_reports_endpoint_not_in_service(make_client):
    with make_client(model=EndpointDown()) as c:
        r = c.get("/ready")
    assert r.status_code == 503 and r.json()["status"] == "not_ready"


def test_ready_when_endpoint_unreachable(make_client):
    class Unreachable(StubModelClient):
        def health(self):
            raise ConnectionError("no route")

    with make_client(model=Unreachable()) as c:
        r = c.get("/ready")
    assert r.status_code == 503 and r.json()["model"]["status"] == "unreachable"


def test_ready_ok_for_stub(make_client):
    with make_client() as c:
        assert c.get("/ready").json()["status"] == "ready"


def test_catalog(make_client, db):
    with make_client() as c:
        body = c.get("/v1/catalog").json()
    assert body["dataset_version"] == db.dataset_version
    assert "rank" in body["operations"] and body["metrics"]["zori"]["regions"] == 2


def test_ask_rank_returns_answer_artifact_and_trace(make_client):
    with make_client() as c:
        r = c.post("/v1/ask", json={"question": "Rank Colorado cities by growth in 2025"})
    body = r.json()
    assert r.status_code == 200 and body["kind"] == "answer"
    assert body["artifact"]["operation"] == "rank"
    assert body["artifact"]["rows_total"] == 4 and body["artifact"]["rows_truncated"] is False
    assert body["artifact"]["period"]["start_month"] == "2025-01-01"
    assert body["trace"][0]["tool"] == "analyze"
    assert body["answer_source"] == "template"  # stub writes no prose


def test_ask_can_omit_rows(make_client):
    with make_client() as c:
        body = c.post(
            "/v1/ask", json={"question": "Rank Colorado cities", "include_rows": False}
        ).json()
    assert body["artifact"]["rows"] == [] and body["artifact"]["rows_total"] == 4


def test_ask_clarifies_ambiguous_city(make_client):
    with make_client() as c:
        body = c.post("/v1/ask", json={"question": "How did Oakwood, OH change?"}).json()
    assert body["kind"] == "clarify" and "Montgomery County" in body["answer"]


def test_request_validation(make_client):
    with make_client() as c:
        assert c.post("/v1/ask", json={"question": ""}).status_code == 422
        assert c.post("/v1/ask", json={"question": "x" * 1001}).status_code == 422


def test_api_key_required_when_configured(make_client):
    with make_client(api_key="s3cret") as c:
        assert c.post("/v1/ask", json={"question": "hi"}).status_code == 401
        assert c.get("/v1/catalog", headers={"X-API-Key": "wrong"}).status_code == 401
        assert c.get("/v1/catalog", headers={"X-API-Key": "s3cret"}).status_code == 200
        assert c.get("/health").status_code == 200  # health stays open


def test_row_cap_constant_is_sane():
    assert MAX_ROWS_IN_RESPONSE >= 1000


def test_state_is_validated(make_client):
    with make_client() as c:
        bad = {"question": "what about rent?", "state": {"metric": "zhvi", "note": "x" * 10_000}}
        assert c.post("/v1/ask", json=bad).status_code == 422
        too_many = {"question": "q", "state": {"cities": [{"city": f"C{i}"} for i in range(21)]}}
        assert c.post("/v1/ask", json=too_many).status_code == 422


def test_updated_state_round_trips_through_the_api(make_client):
    with make_client() as c:
        first = c.post("/v1/ask", json={"question": "What was Mead, CO's highest month?"}).json()
        state = first["updated_state"]
        assert state["cities"][0]["city"] == "Mead"
        follow_up = {"question": "Rank Colorado cities", "state": state}
        assert c.post("/v1/ask", json=follow_up).status_code == 200


def test_ready_reports_the_aws_error_code(make_client):
    """A missing endpoint and a denied call are both ClientErrors; the code tells them apart."""

    class Missing(StubModelClient):
        def health(self):
            from botocore.exceptions import ClientError

            raise ClientError(
                {"Error": {"Code": "ValidationException", "Message": "Could not find endpoint"}},
                "DescribeEndpoint",
            )

    with make_client(model=Missing()) as c:
        model = c.get("/ready").json()["model"]
    assert model == {"status": "unreachable", "error": "ValidationException"}
