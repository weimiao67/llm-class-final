"""App deployment (Step 4c): the EC2 deploy script's configuration and the container layout."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("deploy_app", ROOT / "scripts" / "deploy_app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

ACCOUNT, BUCKET = "123456789012", "sagemaker-us-east-2-123456789012"


def script(**overrides) -> str:
    kwargs = {"bucket": BUCKET, "dataset_version": "23ccd46a4560",
              "endpoint": "final-wm-qwen-lora", "ref": "main"} | overrides  # fmt: skip
    return app.user_data(**kwargs)


# ---- configuration ------------------------------------------------------------------------------


@pytest.mark.parametrize("cidr", ["0.0.0.0/0", "10.0.0.0/8", "2001:db8::/128"])
def test_wide_or_ipv6_ingress_is_refused(cidr):
    with pytest.raises(ValueError, match="too wide"):
        app.check_cidr(cidr)


def test_ingress_opens_only_the_ui_and_api_ports_to_one_address():
    assert app.check_cidr("203.0.113.7/32") == "203.0.113.7/32"
    rules = app.ingress_permissions("203.0.113.7/32")
    assert sorted(r["FromPort"] for r in rules) == [8000, 8501]
    assert all(r["FromPort"] == r["ToPort"] for r in rules)
    assert {ip["CidrIp"] for r in rules for ip in r["IpRanges"]} == {"203.0.113.7/32"}


def test_instance_policy_is_scoped_to_one_endpoint_one_prefix_one_parameter():
    policy = app.instance_policy(ACCOUNT, BUCKET, "Final-WM-Qwen-LoRA")
    statements = {s["Sid"]: s for s in policy["Statement"]}
    assert all(s["Effect"] == "Allow" and "*" not in s["Resource"].split(":")[-1][:1]
               for s in statements.values())  # fmt: skip
    invoke = statements["InvokePlannerEndpoint"]
    assert invoke["Resource"].endswith(f"{ACCOUNT}:endpoint/final-wm-qwen-lora")  # lowercase ARN
    assert set(invoke["Action"]) == {"sagemaker:InvokeEndpoint", "sagemaker:DescribeEndpoint"}
    assert statements["ReadAppData"]["Resource"] == f"arn:aws:s3:::{BUCKET}/llm-final/app-data/*"
    assert statements["ReadAppData"]["Action"] == "s3:GetObject"
    assert statements["ReadApiKey"]["Resource"].endswith(":parameter/llm-final/api-key")
    actions = [a for s in statements.values() for a in [s["Action"]] for a in
               (a if isinstance(a, list) else [a])]  # fmt: skip
    assert not any(a.endswith("*") for a in actions)


def test_user_data_is_valid_bash_and_sets_up_the_app():
    text = script()
    bash = shutil.which("bash")
    if bash:
        subprocess.run([bash, "-n"], input=text, text=True, check=True)
    assert text.startswith("#!/bin/bash\n") and "set -euo pipefail" in text
    assert "sha256sum -c -" in text  # the Compose binary is checksum-verified
    assert "git checkout --quiet main" in text
    assert f"s3://{BUCKET}/llm-final/app-data/23ccd46a4560/" in text
    assert "echo 23ccd46a4560 > data/active_version.txt" in text
    env = re.search(r"cat > \.env <<EOF\n(.*?)\nEOF", text, re.S).group(1).splitlines()
    assert "MODEL_BACKEND=sagemaker" in env and "SAGEMAKER_ENDPOINT_NAME=final-wm-qwen-lora" in env
    assert "API_KEY=$api_key" in env
    assert text.index("umask 077") < text.index("cat > .env")  # the key file is private
    assert "set -x" not in text and "echo $api_key" not in text  # the key never reaches the log
    assert text.rstrip().endswith('echo "setup finished $(date -Is)"')


def test_user_data_deploys_the_requested_ref():
    assert "git checkout --quiet v1.0" in script(ref="v1.0")


def test_compose_checksums_cover_both_instance_architectures():
    assert set(app.COMPOSE_SHA256) == {"x86_64", "aarch64"}
    assert all(re.fullmatch(r"[0-9a-f]{64}", sha) for sha in app.COMPOSE_SHA256.values())


# ---- AWS flows with fake clients ----------------------------------------------------------------


def test_up_refuses_to_launch_a_second_instance():
    ec2 = MagicMock()
    ec2.describe_instances.return_value = {"Reservations": [{"Instances": [
        {"InstanceId": "i-1", "State": {"Name": "stopped"}}]}]}  # fmt: skip
    clients = {"ec2": ec2, "sts": MagicMock(), "s3": MagicMock(), "ssm": MagicMock(),
               "iam": MagicMock()}  # fmt: skip
    args = SimpleNamespace(allow_cidr="203.0.113.7/32", bucket=None, data_dir="data",
                           endpoint="e", instance_profile=None, ref="main",
                           instance_type="t3.small")  # fmt: skip
    assert app.cmd_up(clients, args) == 1
    ec2.run_instances.assert_not_called()
    clients["s3"].upload_file.assert_not_called()


def test_allow_replaces_every_existing_rule():
    ec2 = MagicMock()
    old = [{"IpProtocol": "tcp", "FromPort": 8501, "ToPort": 8501,
            "IpRanges": [{"CidrIp": "198.51.100.1/32"}]}]  # fmt: skip
    ec2.describe_security_groups.return_value = {"SecurityGroups": [{"IpPermissions": old}]}
    app.set_ingress(ec2, "sg-1", "203.0.113.7/32")
    ec2.revoke_security_group_ingress.assert_called_once_with(GroupId="sg-1", IpPermissions=old)
    granted = ec2.authorize_security_group_ingress.call_args.kwargs["IpPermissions"]
    assert granted == app.ingress_permissions("203.0.113.7/32")


def test_instances_require_imdsv2_with_a_hop_for_containers():
    ec2 = MagicMock()
    ec2.run_instances.return_value = {"Instances": [{"InstanceId": "i-1"}]}
    app.run_instance(ec2, ami="ami-1", instance_type="t3.small", group_id="sg-1",
                     profile="p", script="#!/bin/bash")  # fmt: skip
    kwargs = ec2.run_instances.call_args.kwargs
    assert kwargs["MetadataOptions"] == {"HttpTokens": "required", "HttpPutResponseHopLimit": 2}
    assert kwargs["BlockDeviceMappings"][0]["Ebs"]["Encrypted"] is True
    tags = {t["Key"]: t["Value"] for t in kwargs["TagSpecifications"][0]["Tags"]}
    assert tags == {"Name": "llm-final-app", "project": "llm-final", "owner": "wmiao"}


def test_data_upload_skips_objects_already_there(tmp_path):
    (tmp_path / "parquet" / "v1").mkdir(parents=True)
    (tmp_path / "active_version.txt").write_text("v1\n")
    (tmp_path / "parquet" / "v1" / "observations.parquet").write_bytes(b"abc")
    (tmp_path / "parquet" / "v1" / "manifest.json").write_text("{}")
    s3 = MagicMock()
    s3.head_object.side_effect = lambda Bucket, Key: {"ContentLength": 3 if Key.endswith(
        "parquet") else 99}  # fmt: skip
    assert app.upload_data(s3, tmp_path, "b") == "v1"
    uploaded = [c.args[2] for c in s3.upload_file.call_args_list]
    assert uploaded == ["llm-final/app-data/v1/manifest.json"]  # size differs → re-uploaded


def test_up_and_allow_need_a_cidr():
    with pytest.raises(SystemExit):
        app.main(["up"])
    with pytest.raises(SystemExit):
        app.main(["allow", "--allow-cidr", "0.0.0.0/0"])


# ---- container layout ---------------------------------------------------------------------------


def copied_dirs(dockerfile: str, stage: str) -> set[str]:
    body = dockerfile.split(f"AS {stage}\n", 1)[1].split("\nFROM ", 1)[0]
    return set(re.findall(r"^COPY (\w+) \1$", body, re.M))


def imported_top_level(module: str) -> set[str]:
    """Project packages loaded by importing ``module`` (in a fresh interpreter)."""
    code = (f"import sys, json; import {module}; "
            "print(json.dumps(sorted({m.split('.')[0] for m in sys.modules})))")  # fmt: skip
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                         check=True).stdout  # fmt: skip
    project = {p.name for p in ROOT.iterdir() if (p / "__init__.py").exists()}
    return set(json.loads(out)) & project


def test_each_image_copies_the_packages_its_entry_point_imports():
    dockerfile = (ROOT / "Dockerfile").read_text()
    api_dirs = copied_dirs(dockerfile, "api")
    assert imported_top_level("api.main") <= api_dirs
    assert "rag" in api_dirs  # the corpus is data, loaded at startup
    assert imported_top_level("ui.view") | imported_top_level("ui.client") <= copied_dirs(
        dockerfile, "ui"
    )
    allowed = set(re.findall(r"^!(\w+)/$", (ROOT / ".dockerignore").read_text(), re.M))
    assert api_dirs | copied_dirs(dockerfile, "ui") <= allowed


def test_api_image_installs_no_ui_or_dev_groups():
    dockerfile = (ROOT / "Dockerfile").read_text()
    api_stage = dockerfile.split("AS api\n", 1)[1].split("\nFROM ", 1)[0]
    assert "uv sync --locked --no-default-groups --no-install-project" in api_stage
    assert "--group" not in api_stage


# ---- PR #9 review follow-ups --------------------------------------------------------------------


class AWSError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


def fake_clients(*, profile_exists: bool, launch_error: str = "DryRunOperation"):
    ec2, iam, ssm = MagicMock(), MagicMock(), MagicMock()
    ec2.describe_vpcs.return_value = {"Vpcs": [{"VpcId": "vpc-1"}]}
    ec2.describe_instance_types.return_value = {
        "InstanceTypes": [{"ProcessorInfo": {"SupportedArchitectures": ["x86_64", "i386"]}}]
    }
    ec2.create_security_group.side_effect = AWSError("DryRunOperation")
    ec2.run_instances.side_effect = AWSError(launch_error)
    iam.get_role.side_effect = AWSError("NoSuchEntity")
    if not profile_exists:
        iam.get_instance_profile.side_effect = AWSError("NoSuchEntity")

    def get_parameter(Name, **kwargs):
        if Name == app.API_KEY_PARAM:
            raise AWSError("ParameterNotFound")
        return {"Parameter": {"Value": "ami-123"}}

    ssm.get_parameter.side_effect = get_parameter
    sts = MagicMock()
    sts.get_caller_identity.return_value = {"Account": ACCOUNT}
    return {"ec2": ec2, "iam": iam, "ssm": ssm, "s3": MagicMock(), "sts": sts,
            "sagemaker": MagicMock()}  # fmt: skip


def check_args(**overrides):
    defaults = {
        "bucket": None,
        "instance_profile": None,
        "instance_type": "t3.small",
        "endpoint": "e",
    }
    return SimpleNamespace(**(defaults | overrides))


def test_check_dry_runs_the_launch_with_the_role_once_it_exists(capsys):
    clients = fake_clients(profile_exists=True)
    assert app.cmd_check(clients, check_args()) == 0
    kwargs = clients["ec2"].run_instances.call_args.kwargs
    assert kwargs["DryRun"] is True and kwargs["IamInstanceProfile"] == {"Name": app.NAME}
    assert kwargs["ImageId"] == "ami-123"
    out = capsys.readouterr().out
    assert "iam:PassRole" not in out  # checked by the dry run, not listed as unchecked


def test_check_reports_a_passrole_denial(capsys):
    clients = fake_clients(profile_exists=True, launch_error="UnauthorizedOperation")
    assert app.cmd_check(clients, check_args()) == 1
    out = capsys.readouterr().out
    assert "NO   EC2 launch an instance with the app role (dry run): UnauthorizedOperation" in out
    assert "docs/app-deployment.md, 'From the console'" in out


def test_check_never_claims_unprobed_writes_passed(capsys):
    clients = fake_clients(profile_exists=False)
    assert app.cmd_check(clients, check_args()) == 0
    assert "IamInstanceProfile" not in clients["ec2"].run_instances.call_args.kwargs
    out = capsys.readouterr().out
    assert "??   EC2 pass the app role to the instance (iam:PassRole)" in out
    assert "??   IAM create the app role" in out and "??   SSM create the API key" in out
    assert "All checks passed" not in out


def test_console_hint_names_a_real_runbook_section():
    doc = ROOT / "docs" / "app-deployment.md"
    assert "docs/app-deployment.md" in app.CONSOLE_HINT and doc.exists()
    assert "## From the console" in doc.read_text()


def test_image_matches_the_instance_architecture():
    assert app.ami_param("x86_64").endswith("al2023-ami-kernel-default-x86_64")
    assert app.ami_param("arm64").endswith("al2023-ami-kernel-default-arm64")
    with pytest.raises(ValueError):
        app.ami_param("i386")
    ec2, ssm = MagicMock(), MagicMock()
    ec2.describe_instance_types.return_value = {
        "InstanceTypes": [{"ProcessorInfo": {"SupportedArchitectures": ["arm64"]}}]
    }
    ssm.get_parameter.return_value = {"Parameter": {"Value": "ami-arm"}}
    assert app.latest_ami(ssm, ec2, "t4g.small") == "ami-arm"
    assert ssm.get_parameter.call_args.kwargs["Name"] == app.ami_param("arm64")
