"""Deploy-script configuration (pure functions; no AWS calls)."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("deploy", ROOT / "scripts" / "deploy_endpoint.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


def test_hub_model_env_has_messages_api_limits_and_token():
    env = deploy.container_env("meta-llama/Llama-3.2-3B-Instruct", None, "hf_x")
    assert env["HF_MODEL_ID"] == "meta-llama/Llama-3.2-3B-Instruct" and env["HF_TOKEN"] == "hf_x"
    assert env["MESSAGES_API_ENABLED"] == "true"
    assert int(env["MAX_INPUT_TOKENS"]) >= 3072 > 1024  # A7's limit was too small
    assert int(env["MAX_TOTAL_TOKENS"]) > int(env["MAX_INPUT_TOKENS"])


def test_s3_model_env_points_at_unpacked_weights_without_token():
    env = deploy.container_env(None, "s3://b/model.tar.gz", None)
    assert env["HF_MODEL_ID"] == "/opt/ml/model" and "HF_TOKEN" not in env


@pytest.mark.parametrize("hub, data", [(None, None), ("m", "s3://b/m.tar.gz")])
def test_exactly_one_model_source(hub, data):
    with pytest.raises(ValueError, match="exactly one"):
        deploy.container_env(hub, data, "t")


def test_gated_hub_model_needs_token():
    with pytest.raises(ValueError, match="HF_TOKEN"):
        deploy.container_env("meta-llama/Llama-3.2-3B-Instruct", None, None)


def test_specs_share_one_name_and_tag_everything():
    env = deploy.container_env(None, "s3://b/m.tar.gz", None)
    specs = deploy.endpoint_specs(
        "final-wm-x", "img", "arn:role", "ml.g5.2xlarge", env, "s3://b/m.tar.gz"
    )
    assert specs["model"]["ModelName"] == specs["config"]["EndpointConfigName"] == "final-wm-x"
    assert specs["endpoint"]["EndpointConfigName"] == "final-wm-x"
    assert specs["model"]["PrimaryContainer"]["ModelDataUrl"] == "s3://b/m.tar.gz"
    assert specs["config"]["ProductionVariants"][0]["InstanceType"] == "ml.g5.2xlarge"
    for part in specs.values():
        assert {"Key": "project", "Value": "llm-final"} in part["Tags"]


def test_hub_specs_have_no_model_data():
    env = deploy.container_env("m", None, "t")
    specs = deploy.endpoint_specs("n", "img", "r", "ml.g5.2xlarge", env, None)
    assert "ModelDataUrl" not in specs["model"]["PrimaryContainer"]
