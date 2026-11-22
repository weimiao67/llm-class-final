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


# ---- deploy() failure handling, against a stubbed SageMaker client ---------------------------

ARN = "arn:aws:sagemaker:us-east-2:123456789012"
ROLE = "arn:aws:iam::123456789012:role/r"
NAME = "final-wm-x"


@pytest.fixture
def sm(monkeypatch):
    import boto3
    from botocore.stub import Stubber

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    client = boto3.client("sagemaker", region_name="us-east-2")
    with Stubber(client) as stub:
        yield client, stub
        stub.assert_no_pending_responses()


def _specs():
    env = deploy.container_env("m", None, "t")
    return deploy.endpoint_specs(NAME, "img", ROLE, "ml.g5.2xlarge", env, None)


def _missing(stub, *operations):
    for op in operations:
        stub.add_client_error(op, "ValidationException", f"Could not find {op}")


def _nothing_exists(stub):
    _missing(stub, "describe_model", "describe_endpoint_config", "describe_endpoint")


def _creates_succeed(stub):
    stub.add_response("create_model", {"ModelArn": f"{ARN}:model/{NAME}"})
    stub.add_response(
        "create_endpoint_config", {"EndpointConfigArn": f"{ARN}:endpoint-config/{NAME}"}
    )
    stub.add_response("create_endpoint", {"EndpointArn": f"{ARN}:endpoint/{NAME}"})


def test_refuses_to_deploy_over_leftovers(sm, capsys):
    client, stub = sm
    model = {
        "ModelName": NAME,
        "ModelArn": f"{ARN}:model/{NAME}",
        "CreationTime": "2026-11-20",
        "ExecutionRoleArn": ROLE,
    }
    stub.add_response("describe_model", model)
    _missing(stub, "describe_endpoint_config", "describe_endpoint")
    assert deploy.deploy(client, _specs(), wait=False) == 1
    out = capsys.readouterr().out
    assert f"model named '{NAME}' already exist" in out and f"--delete --name {NAME}" in out


def test_partial_create_failure_names_what_to_clean_up(sm, capsys):
    client, stub = sm
    _nothing_exists(stub)
    stub.add_response("create_model", {"ModelArn": f"{ARN}:model/{NAME}"})
    stub.add_client_error("create_endpoint_config", "ResourceLimitExceeded", "quota exceeded")
    assert deploy.deploy(client, _specs(), wait=False) == 1
    out = capsys.readouterr().out
    assert "quota exceeded" in out and "Already created: model" in out and "--delete" in out


def test_successful_no_wait_deploy(sm, capsys):
    client, stub = sm
    _nothing_exists(stub)
    _creates_succeed(stub)
    assert deploy.deploy(client, _specs(), wait=False) == 0
    assert "billing starts now" in capsys.readouterr().out


def test_failed_endpoint_reports_status_and_delete_hint(sm, capsys):
    client, stub = sm
    _nothing_exists(stub)
    _creates_succeed(stub)
    failed = {
        "EndpointName": NAME,
        "EndpointArn": f"{ARN}:endpoint/{NAME}",
        "EndpointStatus": "Failed",
        "FailureReason": "CUDA out of memory",
        "CreationTime": "2026-11-20",
        "LastModifiedTime": "2026-11-20",
    }
    stub.add_response("describe_endpoint", failed)  # the waiter sees Failed and stops
    stub.add_response("describe_endpoint", failed)  # status() after the failure
    assert deploy.deploy(client, _specs(), wait=True) == 1
    out = capsys.readouterr().out
    assert "did not reach InService" in out and "CUDA out of memory" in out
    assert "may still be billing" in out and f"--delete --name {NAME}" in out


# ---- capacity fallback and wait sizing -------------------------------------------------------


def test_single_type_variant_is_unchanged_by_default():
    v = deploy.production_variant(NAME, "ml.g5.2xlarge", [], None)
    assert v["InstanceType"] == "ml.g5.2xlarge"
    assert "InstancePools" not in v and "VariantInstanceProvisionTimeoutInSeconds" not in v


def test_fallbacks_become_prioritized_instance_pools():
    v = deploy.production_variant(
        NAME, "ml.g5.2xlarge", ["ml.g6.2xlarge", "ml.g5.2xlarge", "ml.g6e.xlarge"], None
    )
    assert "InstanceType" not in v
    assert v["InstancePools"] == [
        {"InstanceType": "ml.g5.2xlarge", "Priority": 1},
        {"InstanceType": "ml.g6.2xlarge", "Priority": 2},
        {"InstanceType": "ml.g6e.xlarge", "Priority": 3},
    ]
    assert v["VariantInstanceProvisionTimeoutInSeconds"] == deploy.FALLBACK_PROVISION_TIMEOUT_S


def test_pool_and_timeout_limits():
    with pytest.raises(ValueError, match="at most 5"):
        deploy.production_variant(NAME, "a", ["b", "c", "d", "e", "f"], None)
    with pytest.raises(ValueError, match="300-3600"):
        deploy.production_variant(NAME, "a", [], 120)


def test_wait_covers_every_sagemaker_timeout():
    # Old bug: a fixed 30 min wait was shorter than download (20) + startup check (15) alone.
    for provision in (None, 300, 3600):
        waited = deploy.wait_attempts(provision) * deploy.WAIT_DELAY_S
        covered = (
            (provision or deploy.DEFAULT_PROVISION_TIMEOUT_S)
            + deploy.MODEL_DOWNLOAD_TIMEOUT_S
            + deploy.STARTUP_HEALTH_CHECK_TIMEOUT_S
        )
        assert waited > covered


def test_pinned_boto3_supports_instance_pools(sm):
    client, _ = sm
    assert deploy.supports_instance_pools(client)


def _pool_specs():
    env = deploy.container_env("m", None, "t")
    return deploy.endpoint_specs(
        NAME, "img", ROLE, "ml.g5.2xlarge", env, None, fallbacks=["ml.g6.2xlarge"]
    )


def test_config_retries_with_instance_type_if_service_requires_it(sm, capsys):
    client, stub = sm
    config = _pool_specs()["config"]
    stub.add_client_error(
        "create_endpoint_config", "ValidationException", "InstanceType is required"
    )
    retried = {
        **config,
        "ProductionVariants": [
            {**config["ProductionVariants"][0], "InstanceType": "ml.g5.2xlarge"}
        ],
    }
    stub.add_response(
        "create_endpoint_config", {"EndpointConfigArn": f"{ARN}:endpoint-config/{NAME}"}, retried
    )
    deploy.create_config(client, config)
    assert "Retrying endpoint config with InstanceType set" in capsys.readouterr().out


def test_config_does_not_retry_unrelated_errors(sm):
    client, stub = sm
    stub.add_client_error("create_endpoint_config", "ResourceLimitExceeded", "quota exceeded")
    with pytest.raises(client.exceptions.ClientError):
        deploy.create_config(client, _pool_specs()["config"])
