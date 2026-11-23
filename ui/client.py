"""HTTP client for the agent API. The UI talks to the agent only through this, like any client.

Failures become ``APIError`` with a message a user can act on; the UI shows it instead of a
traceback.
"""

from __future__ import annotations

from typing import Any

import httpx

# A turn can make several model calls (plan, retries, answer); the API's own turn budget is
# shorter than this, so the client doesn't give up first.
ASK_TIMEOUT_S = 120.0
STATUS_TIMEOUT_S = 10.0
MAX_HISTORY_MESSAGES = 20  # API limits (api/main.py AskRequest)
MAX_MESSAGE_CHARS = 4000


class APIError(Exception):
    """A request to the agent API failed; ``str(err)`` is meant for the user."""


class AnalystClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        headers = {"X-API-Key": api_key} if api_key else {}
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(base_url=self.base_url, headers=headers, transport=transport)

    def ask(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        history = [
            {"role": m["role"], "content": m["content"][:MAX_MESSAGE_CHARS]}
            for m in (history or [])[-MAX_HISTORY_MESSAGES:]
        ]
        body = {"question": question, "history": history, "state": state or {}}
        return self._request("POST", "/v1/ask", json=body, timeout=ASK_TIMEOUT_S)

    def catalog(self) -> dict[str, Any]:
        return self._request("GET", "/v1/catalog", timeout=STATUS_TIMEOUT_S)

    def ready(self) -> dict[str, Any]:
        """Readiness body. A 503 is a normal answer here (model endpoint not InService)."""
        return self._request("GET", "/ready", timeout=STATUS_TIMEOUT_S, ok=(200, 503))

    def _request(self, method: str, path: str, ok=(200,), **kwargs) -> dict[str, Any]:
        try:
            r = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise APIError("The agent API took too long to respond. Try again.") from exc
        except httpx.HTTPError as exc:
            raise APIError(f"Can't reach the agent API at {self.base_url}.") from exc
        if r.status_code in ok:
            try:
                return r.json()
            except ValueError as exc:  # e.g. a proxy's plain-text 503 while the API starts
                raise APIError("The agent API returned an unexpected response.") from exc
        if r.status_code == 401:
            raise APIError("The agent API rejected the API key (set ANALYST_API_KEY).")
        if r.status_code == 422:
            raise APIError(f"The agent API rejected the request: {_detail(r)}")
        raise APIError(f"The agent API returned HTTP {r.status_code}.")


def _detail(r: httpx.Response) -> str:
    try:
        detail = r.json().get("detail")
    except ValueError:
        return r.text[:200]
    if isinstance(detail, list) and detail:
        return "; ".join(str(d.get("msg", d)) for d in detail[:3])
    return str(detail)
