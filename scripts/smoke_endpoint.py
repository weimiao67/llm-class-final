"""Check a live TGI endpoint against the request settings the agent relies on (design doc §10).

Checks, using the real planner prompt:
  1. constrained greedy planning: TGI accepts `response_format` with the ToolCall JSON Schema,
     and the reply parses as a valid tool call
  2. greedy is deterministic: the same request twice gives the same text
  3. unconstrained planning still answers (needed for the "no constraint" ablation rows)
  4. sampled answer writing (temperature 0.3, top_p 0.9) returns text

Usage (Studio terminal, repo root, endpoint InService):
    uv run python scripts/smoke_endpoint.py --endpoint final-wm-llama32-3b-base
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from agent import decoding
from agent.model_clients.sagemaker import SageMakerModelClient
from agent.prompts import answer_messages, planner_messages
from housing.db import HousingDB
from tools.schemas import ToolCall, tool_call_json_schema

QUESTION = "Rank Colorado cities by ZHVI growth in 2025."


def check(label: str, fn) -> bool:
    try:
        ok, detail = fn()
    except Exception as exc:  # show TGI's validation message (e.g. unsupported schema feature)
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    print(f"[{'PASS' if ok else 'FAIL'}] {label}\n       {detail}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--region", default="us-east-2")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()

    client = SageMakerModelClient(args.endpoint, region=args.region)
    print("endpoint:", client.health())
    messages = planner_messages(HousingDB(args.data_dir), QUESTION, [], None)
    schema = tool_call_json_schema()

    def parse(text: str) -> str:
        call = ToolCall.model_validate_json(text).call
        return f"tool={call.tool} " + json.dumps(call.model_dump(exclude_none=True))[:200]

    outputs: list[str] = []

    def constrained():
        out = client.complete(messages, decoding.PLAN, schema)
        outputs.append(out.text)
        return True, f"{out.latency_ms:.0f} ms, {out.usage} → {parse(out.text)}"

    def deterministic():
        again = client.complete(messages, decoding.PLAN, schema).text
        return again == outputs[0], "identical" if again == outputs[0] else f"differs: {again!r}"

    def unconstrained():
        profile = dataclasses.replace(decoding.PLAN, constrained=False)
        out = client.complete(messages, profile, None)
        try:
            return True, f"{out.latency_ms:.0f} ms → {parse(out.text)}"
        except ValidationError:
            # Not a transport failure: the model answered but without a valid tool call. That is
            # exactly what the constrained/unconstrained ablation measures.
            return True, f"reply is not a valid tool call (expected sometimes): {out.text[:200]!r}"

    def answer():
        evidence = {"summary": {"top": [{"city": "Telluride", "pct_change": 8.95}]}}
        out = client.complete(answer_messages(QUESTION, evidence), decoding.ANSWER)
        return bool(out.text.strip()), f"{out.latency_ms:.0f} ms → {out.text[:200]!r}"

    results = [check("constrained greedy plan parses as a tool call", constrained)]
    if results[0]:
        results.append(check("greedy decoding is deterministic", deterministic))
    results.append(check("unconstrained plan request succeeds", unconstrained))
    results.append(check("sampled answer returns text", answer))
    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
