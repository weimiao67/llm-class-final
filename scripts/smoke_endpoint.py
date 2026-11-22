"""Check a live TGI endpoint against the request settings the agent relies on (design doc §10).

Checks run from simplest to riskiest, so a failure says where the problem is:
  1. unconstrained plan request (no schema): is the server answering at all?
  2. sampled answer writing (temperature 0.3, top_p 0.9) returns text
  3. constrained greedy planning: TGI accepts `response_format` with the decoding schema, and the
     reply has the schema's shape. Whether the plan also passes full validation (e.g. "exactly
     one of cities or state_filter", which a JSON Schema can't express) is a model-quality
     result, reported but not failed here; the eval measures it.
  4. the constraint is really enforced (negative control): asked to reply "hello", the model
     still returns a schema-shaped tool call when the schema is sent, and plain text when it
     isn't. Check 3 alone can't show this, because the planner prompt already asks for JSON.
  5. greedy is deterministic: the same request twice gives the same text

Requests are not retried (a timed-out request re-sent would queue behind itself), and each may
take up to --timeout seconds (SageMaker real-time invocations are capped at 60 s).

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
from tools.schemas import ToolCall, decoding_schema

QUESTION = "Rank Colorado cities by ZHVI growth in 2025."
CONTROL = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Reply with only the word hello. Do not output JSON."},
]


def check(label: str, fn) -> bool:
    try:
        ok, detail = fn()
    except Exception as exc:  # show TGI's validation message (e.g. unsupported schema feature)
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    print(f"[{'PASS' if ok else 'FAIL'}] {label}\n       {detail}", flush=True)
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--region", default="us-east-2")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--timeout", type=int, default=65, help="seconds per request")
    args = parser.parse_args()

    client = SageMakerModelClient(
        args.endpoint, region=args.region, timeout_s=args.timeout, total_attempts=1
    )
    try:
        health = client.health()
    except Exception as exc:
        print(f"Endpoint {args.endpoint!r} not reachable ({type(exc).__name__}: {exc}).")
        print("Check it with: python scripts/deploy_endpoint.py --status --name <name>")
        return 2
    if health["status"] != "InService":
        print(f"Endpoint {args.endpoint!r} is {health['status']}, not InService; try again later.")
        return 2
    print("endpoint:", health, flush=True)
    messages = planner_messages(HousingDB(args.data_dir), QUESTION, [], None)
    schema = decoding_schema()
    unconstrained_plan = dataclasses.replace(decoding.PLAN, constrained=False)

    def shaped(text: str) -> str:
        """Raise unless ``text`` has the decoding schema's top-level shape; return the tool."""
        call = json.loads(text)["call"]
        if call.get("tool") not in {"analyze", "search_knowledge", "respond"}:
            raise ValueError(f"unknown tool {call.get('tool')!r}")
        return call["tool"]

    def describe(text: str) -> str:
        """Shape and full-validation status of a planner reply, for the report."""
        try:
            tool = shaped(text)
        except (ValueError, KeyError, TypeError) as exc:
            return f"not schema-shaped ({type(exc).__name__}): {text[:200]!r}"
        try:
            ToolCall.model_validate_json(text)
            return f"tool={tool}, valid plan: {text[:200]}"
        except ValidationError as exc:
            first = exc.errors()[0]
            return f"tool={tool}, fails validation ({first['msg']}): {text[:200]}"

    def unconstrained():
        out = client.complete(messages, unconstrained_plan, None)
        # Passing means the server answered; reply quality is what the ablation measures.
        return True, f"{out.latency_ms:.0f} ms → {describe(out.text)}"

    def answer():
        evidence = {"summary": {"top": [{"city": "Telluride", "pct_change": 8.95}]}}
        out = client.complete(answer_messages(QUESTION, evidence), decoding.ANSWER)
        return bool(out.text.strip()), f"{out.latency_ms:.0f} ms → {out.text[:200]!r}"

    outputs: list[str] = []

    def constrained():
        out = client.complete(messages, decoding.PLAN, schema)
        outputs.append(out.text)
        shaped(out.text)  # raises (check fails) if the constraint didn't shape the reply
        return True, f"{out.latency_ms:.0f} ms, {out.usage} → {describe(out.text)}"

    def enforced():
        with_schema = client.complete(CONTROL, decoding.PLAN, schema).text
        try:
            tool = shaped(with_schema)
        except (ValueError, KeyError, TypeError):
            return False, f"constraint NOT applied: schema sent, model replied {with_schema!r}"
        without = client.complete(CONTROL, unconstrained_plan, None).text
        try:
            shaped(without)
            control = "inconclusive: the model returned a tool call even without the schema"
        except (ValueError, KeyError, TypeError):
            control = f"without schema it replied {without[:60]!r}"
        return True, f"schema forced a tool call (tool={tool}); {control}"

    def deterministic():
        again = client.complete(messages, decoding.PLAN, schema).text
        return again == outputs[0], "identical" if again == outputs[0] else f"differs: {again!r}"

    server_ok = check("server answers an unconstrained plan request", unconstrained)
    if not server_ok:
        print(
            "\nThe server doesn't answer even without a schema: check the endpoint logs\n"
            "(aws logs tail /aws/sagemaker/Endpoints/<name> --since 30m). If an earlier run\n"
            "sent a schema, TGI may still be compiling it; wait a few minutes and retry."
        )
        return 1
    results = [server_ok, check("sampled answer returns text", answer)]
    results.append(check("constrained greedy plan has the schema's shape", constrained))
    if results[-1]:
        results.append(check("schema constraint is enforced (negative control)", enforced))
        results.append(check("greedy decoding is deterministic", deterministic))
    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) and len(results) == 5 else 1


if __name__ == "__main__":
    sys.exit(main())
