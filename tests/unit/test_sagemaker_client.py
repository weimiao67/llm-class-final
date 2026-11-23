import io
import json

from agent.decoding import ANSWER, PLAN
from agent.model_clients.sagemaker import SageMakerModelClient


class FakeRuntime:
    def __init__(self, reply):
        self.reply = reply
        self.requests = []

    def invoke_endpoint(self, **kwargs):
        self.requests.append(kwargs)
        return {"Body": io.BytesIO(json.dumps(self.reply).encode())}


class FakeSageMaker:
    def describe_endpoint(self, EndpointName):
        return {"EndpointStatus": "InService"}


REPLY = {
    "choices": [{"message": {"role": "assistant", "content": '{"call": {}}'}}],
    "usage": {"prompt_tokens": 900, "completion_tokens": 40, "total_tokens": 940},
}


def client(runtime):
    return SageMakerModelClient(
        "final-wm-planner-v1", runtime_client=runtime, sagemaker_client=FakeSageMaker()
    )


def test_plan_request_is_greedy_and_schema_constrained():
    runtime = FakeRuntime(REPLY)
    out = client(runtime).complete([{"role": "user", "content": "hi"}], PLAN, {"type": "object"})
    req = runtime.requests[0]
    body = json.loads(req["Body"])
    assert req["EndpointName"] == "final-wm-planner-v1"
    assert body["temperature"] == 0.0 and body["max_tokens"] == 256
    assert body["response_format"] == {"type": "json_object", "value": {"type": "object"}}
    assert out.text == '{"call": {}}'
    assert out.usage == {"prompt_tokens": 900, "completion_tokens": 40}


def test_answer_request_samples_without_constraint():
    runtime = FakeRuntime(REPLY)
    client(runtime).complete([{"role": "user", "content": "hi"}], ANSWER, None)
    body = json.loads(runtime.requests[0]["Body"])
    assert (body["temperature"], body["top_p"]) == (0.3, 0.9)
    assert "response_format" not in body


def test_null_content_becomes_empty_text():
    reply = {"choices": [{"message": {"content": None}}]}
    out = client(FakeRuntime(reply)).complete([], ANSWER)
    assert out.text == "" and out.usage == {}


def test_health_reports_endpoint_status():
    assert client(FakeRuntime(REPLY)).health()["status"] == "InService"


def test_attempts_count_the_first_try():
    # botocore's "max_attempts" counts retries only (2 -> 3 sends); total_max_attempts doesn't.
    default = SageMakerModelClient("e", sagemaker_client=FakeSageMaker())
    assert default._runtime.meta.config.retries["total_max_attempts"] == 2
    once = SageMakerModelClient("e", sagemaker_client=FakeSageMaker(), total_attempts=1)
    assert once._runtime.meta.config.retries["total_max_attempts"] == 1
