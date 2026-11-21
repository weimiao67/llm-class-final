"""Agent HTTP API (design doc §14). OpenAPI docs are served at /docs.

Endpoints: POST /v1/ask, GET /v1/catalog, GET /health (liveness), GET /ready (readiness).

Run locally with the stub model:
    MODEL_BACKEND=stub uv run uvicorn api.main:app --reload
Against a deployed SageMaker endpoint:
    MODEL_BACKEND=sagemaker SAGEMAKER_ENDPOINT_NAME=<name> uv run uvicorn api.main:app
"""

from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent.model_clients.stub import StubModelClient, demo_rules
from agent.orchestrator import Agent
from housing.db import HousingDB
from tools.operations import OPERATIONS
from tools.schemas import TOOL_PROTOCOL_VERSION, ConversationState

MAX_ROWS_IN_RESPONSE = 5000


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(max_length=4000)]


class AskRequest(BaseModel):
    question: Annotated[str, Field(min_length=1, max_length=1000)]
    history: Annotated[list[Message], Field(max_length=20)] = []
    state: ConversationState = ConversationState()
    include_rows: bool = True


def build_agent_from_env() -> Agent:
    db = HousingDB(os.environ.get("DATA_DIR", "data"))
    backend = os.environ.get("MODEL_BACKEND", "stub")
    if backend == "stub":
        model = StubModelClient(rules=demo_rules())
    elif backend == "sagemaker":
        from agent.model_clients.sagemaker import SageMakerModelClient

        endpoint = os.environ["SAGEMAKER_ENDPOINT_NAME"]
        model = SageMakerModelClient(
            endpoint_name=endpoint,
            model_id=os.environ.get("MODEL_ID", endpoint),
            region=os.environ.get("AWS_REGION", "us-east-2"),
        )
    else:
        raise ValueError(f"MODEL_BACKEND must be 'stub' or 'sagemaker', got {backend!r}")
    return Agent(db, model)


# Dependencies live at module level: with postponed annotations, FastAPI resolves
# ``Depends(...)`` targets from module globals, so nested functions would not be found.
def get_agent(request: Request) -> Agent:
    return request.app.state.agent


def require_key(request: Request, x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = request.app.state.api_key
    if expected and not (x_api_key and secrets.compare_digest(x_api_key, expected)):
        raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")


def create_app(agent: Agent | None = None, api_key: str | None = None) -> FastAPI:
    api_key = api_key if api_key is not None else os.environ.get("API_KEY") or None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.agent = agent or build_agent_from_env()
        yield

    app = FastAPI(title="Housing Market AI Analyst", version="0.2.0", lifespan=lifespan)
    app.state.api_key = api_key

    @app.get("/health")
    def health(agent: Annotated[Agent, Depends(get_agent)]):
        """Liveness: the process is up and the dataset is loaded. Always 200 while serving, so
        host health checks don't restart the app when the (often deleted) endpoint is down."""
        return {
            "status": "ok",
            "dataset_version": agent.db.dataset_version,
            "model_id": agent.model.model_id,
        }

    @app.get("/ready")
    def ready(agent: Annotated[Agent, Depends(get_agent)]):
        """Readiness: can a question be answered right now? 503 when the model endpoint isn't
        InService. Use this for UI status, not for host health checks."""
        body: dict[str, Any] = {
            "dataset_version": agent.db.dataset_version,
            "model_id": agent.model.model_id,
        }
        ready_now = True
        check = getattr(agent.model, "health", None)
        if check is not None:
            try:
                body["model"] = check()
                ready_now = body["model"].get("status") == "InService"
            except Exception as exc:  # report, don't crash the readiness check
                body["model"] = {"status": "unreachable", "error": type(exc).__name__}
                ready_now = False
        body["status"] = "ready" if ready_now else "not_ready"
        return JSONResponse(body, status_code=200 if ready_now else 503)

    @app.get("/v1/catalog", dependencies=[Depends(require_key)])
    def catalog(agent: Annotated[Agent, Depends(get_agent)]):
        db = agent.db
        return {
            "dataset_version": db.dataset_version,
            "tool_protocol_version": TOOL_PROTOCOL_VERSION,
            "metrics": {
                m: {
                    "first_month": c.first_month.isoformat(),
                    "last_month": c.last_month.isoformat(),
                    "regions": c.regions,
                    "observations": c.observations,
                }
                for m, c in db.coverage.items()
            },
            "operations": sorted(OPERATIONS),
            "sources": db.source_files(),
        }

    @app.post("/v1/ask", dependencies=[Depends(require_key)])
    def ask(req: AskRequest, agent: Annotated[Agent, Depends(get_agent)]):
        # Sync handler: FastAPI runs it in a worker thread, so blocking model calls are fine.
        result = agent.run_turn(
            req.question,
            history=[m.model_dump() for m in req.history],
            state=req.state.model_dump(exclude_defaults=True),
        )
        body = result.model_dump(mode="json")
        art = body.get("artifact")
        if art is not None:
            total = len(art["rows"])
            if not req.include_rows:
                art["rows"] = []
            elif total > MAX_ROWS_IN_RESPONSE:
                art["rows"] = art["rows"][:MAX_ROWS_IN_RESPONSE]
            art["rows_total"] = total
            art["rows_truncated"] = len(art["rows"]) < total
        return body

    return app


app = create_app()
