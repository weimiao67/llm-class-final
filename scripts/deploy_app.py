"""Deploy the app (agent API + Streamlit UI) to one small EC2 instance, and manage it.

Run in a SageMaker Studio terminal from the repo root, with Studio's own python (boto3 only; it
imports nothing from this repo). The instance clones the public repo, copies the dataset from S3,
and runs `docker compose`. It calls the SageMaker endpoint with its own narrowly scoped role.

    python scripts/deploy_app.py check                     # what this Studio role may do
    python scripts/deploy_app.py up --allow-cidr <your-ip>/32
    python scripts/deploy_app.py status                    # URLs; setup takes ~5 min after boot
    python scripts/deploy_app.py allow --allow-cidr <new-ip>/32   # your IP changed
    python scripts/deploy_app.py stop | start              # stop when not demoing (~$0.02/h)
    python scripts/deploy_app.py down                      # delete everything this script made
    python scripts/deploy_app.py user-data > user-data.sh  # for launching from the console
    python scripts/deploy_app.py policy                    # the instance role's policy (console)

The model endpoint is separate: deploy it with scripts/deploy_endpoint.py under the name given
by --endpoint (default below), and delete it after each session as usual. The app stays up and
reports the endpoint as not ready while it is deleted.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import secrets
import sys
import time
from pathlib import Path
from typing import Any

REGION = "us-east-2"
NAME = "llm-final-app"  # instance Name tag, security group, role, instance profile
TAGS = [{"Key": "project", "Value": "llm-final"}, {"Key": "owner", "Value": "wmiao"}]
DEFAULT_ENDPOINT = "final-wm-qwen-lora"
DEFAULT_INSTANCE_TYPE = "t3.small"  # 2 vCPU, 2 GiB: enough for DuckDB over ~40 MB of Parquet
REPO_URL = "https://github.com/weimiao67/llm-class-final.git"
API_KEY_PARAM = "/llm-final/api-key"
DATA_PREFIX = "llm-final/app-data"  # s3://<bucket>/<prefix>/<dataset version>/...
# Latest Amazon Linux 2023 image per CPU architecture (EC2 name -> SSM public parameter suffix).
AMI_PARAM = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-{arch}"
AMI_ARCHES = {"x86_64": "x86_64", "arm64": "arm64"}
PORTS = {"ui": 8501, "api": 8000}
MIN_CIDR_PREFIX = 16  # refuse rules that open the app to (nearly) the whole internet
SSM_CORE_POLICY = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"  # Session Manager shell
# Docker CLI plugins, pinned and checksum-verified (Amazon Linux's docker package has neither).
# Compose v2.17+ builds images through buildx and refuses to without buildx >= 0.17.
COMPOSE_VERSION = "v5.6.1"
BUILDX_VERSION = "v0.38.1"
# Keyed by `uname -m`; each entry is (file-name architecture, sha256).
COMPOSE_ASSETS = {
    "x86_64": ("x86_64", "47737f4236e6d3ccea7291995203f8f018058783b4c3a9469119811a0b5db8c0"),
    "aarch64": ("aarch64", "42cfa75f51ad0ccf290bad37899e0038a8c10a0069e85233ecc1d53e3ff1347d"),
}
BUILDX_ASSETS = {
    "x86_64": ("amd64", "e25d5cd675092bb5d1d03632fdc46cdf3fede7b514dc5f023a105e00d3ce5ad4"),
    "aarch64": ("arm64", "3b83b3731916ba433feccaaa689fe5bcdc81c641d92c8e6c2ea865dfa141c97a"),
}
LIVE_STATES = ["pending", "running", "stopping", "stopped"]


# ---- pure configuration (unit-tested) -----------------------------------------------------------


def default_bucket(account: str, region: str = REGION) -> str:
    """The SageMaker default bucket Studio already writes to."""
    return f"sagemaker-{region}-{account}"


def check_cidr(cidr: str) -> str:
    net = ipaddress.ip_network(cidr, strict=False)
    if net.version != 4 or net.prefixlen < MIN_CIDR_PREFIX:
        raise ValueError(
            f"--allow-cidr {cidr} is too wide; use your own IPv4 address, e.g. 203.0.113.7/32"
        )
    return str(net)


def ingress_permissions(cidr: str) -> list[dict[str, Any]]:
    return [
        {
            "IpProtocol": "tcp",
            "FromPort": port,
            "ToPort": port,
            "IpRanges": [{"CidrIp": cidr, "Description": f"{NAME} {name}"}],
        }
        for name, port in PORTS.items()
    ]


def instance_policy(account: str, bucket: str, endpoint: str, region: str = REGION) -> dict:
    """The instance role may call one endpoint, read the app data, and read the API key."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "InvokePlannerEndpoint",
                "Effect": "Allow",
                "Action": ["sagemaker:InvokeEndpoint", "sagemaker:DescribeEndpoint"],
                # Endpoint ARNs are lowercase.
                "Resource": f"arn:aws:sagemaker:{region}:{account}:endpoint/{endpoint.lower()}",
            },
            {
                "Sid": "ReadAppData",
                "Effect": "Allow",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket}/{DATA_PREFIX}/*",
            },
            {
                "Sid": "ListAppData",
                "Effect": "Allow",
                "Action": "s3:ListBucket",
                "Resource": f"arn:aws:s3:::{bucket}",
                "Condition": {"StringLike": {"s3:prefix": [f"{DATA_PREFIX}/*"]}},
            },
            {
                "Sid": "ReadApiKey",
                "Effect": "Allow",
                "Action": "ssm:GetParameter",
                "Resource": f"arn:aws:ssm:{region}:{account}:parameter{API_KEY_PARAM}",
            },
        ],
    }


EC2_TRUST = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "ec2.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }
    ],
}


def user_data(
    *, bucket: str, dataset_version: str, endpoint: str, ref: str, region: str = REGION
) -> str:
    """First-boot script: Docker + Compose, the repo at ``ref``, the data, .env, compose up.

    Containers restart on reboot (restart: unless-stopped), so stop/start needs no script. The
    API key is read from SSM into a 0600 .env file and never echoed into the setup log.
    """
    cases = "\n".join(
        f"  {arch}) compose_arch={COMPOSE_ASSETS[arch][0]} compose_sha={COMPOSE_ASSETS[arch][1]}"
        f" buildx_arch={BUILDX_ASSETS[arch][0]} buildx_sha={BUILDX_ASSETS[arch][1]} ;;"
        for arch in COMPOSE_ASSETS
    )
    return f"""#!/bin/bash
# {NAME} first-boot setup (generated by scripts/deploy_app.py).
# Progress goes to /var/log/{NAME}-setup.log and to the console, so EC2's "Get system log" shows
# where setup stopped even when Session Manager isn't working.
set -Eeuo pipefail
log=/var/log/{NAME}-setup.log
# tee keeps writing the log file even if the console can't be written, so logging can never stop
# the setup (a dead log pipe would kill every later command with SIGPIPE).
console=/dev/null
[ -w /dev/console ] && console=/dev/console
exec > >(tee -a "$log" "$console" >/dev/null) 2>&1
trap 'echo "[{NAME}] SETUP FAILED (exit $?) at line $LINENO: $BASH_COMMAND"' ERR
step() {{ echo "[{NAME}] $(date -Is) $*"; }}
step "setup started"

step "installing docker and git"
dnf install -y -q docker git
systemctl enable --now docker

step "installing docker compose {COMPOSE_VERSION} and buildx {BUILDX_VERSION}"
arch=$(uname -m)
case "$arch" in
{cases}
  *) echo "unsupported architecture $arch"; exit 1 ;;
esac
install_plugin() {{  # name url sha256
  local path=/usr/local/lib/docker/cli-plugins/$1
  mkdir -p "$(dirname "$path")"
  curl -fsSL -o "$path" "$2"
  echo "$3  $path" | sha256sum -c -
  chmod +x "$path"
}}
compose_url=https://github.com/docker/compose/releases/download/{COMPOSE_VERSION}
buildx_url=https://github.com/docker/buildx/releases/download/{BUILDX_VERSION}
install_plugin docker-compose "$compose_url/docker-compose-linux-$compose_arch" "$compose_sha"
install_plugin docker-buildx "$buildx_url/buildx-{BUILDX_VERSION}.linux-$buildx_arch" "$buildx_sha"
docker compose version
docker buildx version

step "cloning the app at {ref}"
app=/opt/{NAME}
git clone --quiet {REPO_URL} "$app"
cd "$app"
git checkout --quiet {ref}
echo "code at $(git rev-parse HEAD)"

step "copying dataset {dataset_version} from s3://{bucket}/{DATA_PREFIX}/"
mkdir -p data/parquet/{dataset_version}
aws s3 cp --only-show-errors --recursive \\
  s3://{bucket}/{DATA_PREFIX}/{dataset_version}/ data/parquet/{dataset_version}/
echo {dataset_version} > data/active_version.txt

step "reading the API key from {API_KEY_PARAM}"
api_key=$(aws ssm get-parameter --region {region} --name {API_KEY_PARAM} --with-decryption \\
  --query Parameter.Value --output text)
umask 077
cat > .env <<EOF
MODEL_BACKEND=sagemaker
SAGEMAKER_ENDPOINT_NAME={endpoint}
MODEL_ID={endpoint}
AWS_REGION={region}
API_KEY=$api_key
EOF
umask 022

step "building and starting the app (about 5 minutes)"
docker compose up -d --build
step "setup finished"
"""


def app_urls(public_dns: str | None) -> dict[str, str]:
    if not public_dns:
        return {}
    return {name: f"http://{public_dns}:{port}" for name, port in PORTS.items()}


# ---- AWS operations -----------------------------------------------------------------------------


def find_instance(ec2) -> dict | None:
    r = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Name", "Values": [NAME]},
            {"Name": "tag:project", "Values": ["llm-final"]},
            {"Name": "instance-state-name", "Values": LIVE_STATES},
        ]
    )
    instances = [i for res in r["Reservations"] for i in res["Instances"]]
    return instances[0] if instances else None


def default_vpc(ec2) -> str:
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"]
    if not vpcs:
        raise SystemExit("No default VPC in this Region; create one (VPC console) or ask for help.")
    return vpcs[0]["VpcId"]


def find_security_group(ec2, vpc_id: str) -> str | None:
    groups = ec2.describe_security_groups(
        Filters=[{"Name": "group-name", "Values": [NAME]}, {"Name": "vpc-id", "Values": [vpc_id]}]
    )["SecurityGroups"]
    return groups[0]["GroupId"] if groups else None


def set_ingress(ec2, group_id: str, cidr: str) -> None:
    """Replace the group's inbound rules with the UI and API ports from ``cidr`` only."""
    current = ec2.describe_security_groups(GroupIds=[group_id])["SecurityGroups"][0]
    if current["IpPermissions"]:
        ec2.revoke_security_group_ingress(GroupId=group_id, IpPermissions=current["IpPermissions"])
    ec2.authorize_security_group_ingress(GroupId=group_id, IpPermissions=ingress_permissions(cidr))


def ensure_security_group(ec2, cidr: str) -> str:
    vpc_id = default_vpc(ec2)
    group_id = find_security_group(ec2, vpc_id)
    if group_id is None:
        group_id = ec2.create_security_group(
            GroupName=NAME,
            Description="Housing analyst app: UI and API from one allowed address",
            VpcId=vpc_id,
            TagSpecifications=[{"ResourceType": "security-group", "Tags": TAGS}],
        )["GroupId"]
        print(f"created security group {group_id}")
    set_ingress(ec2, group_id, cidr)
    return group_id


def ensure_instance_profile(iam, policy: dict) -> str:
    try:
        iam.get_role(RoleName=NAME)
    except iam.exceptions.NoSuchEntityException:
        iam.create_role(
            RoleName=NAME,
            AssumeRolePolicyDocument=json.dumps(EC2_TRUST),
            Description="Housing analyst app instance role",
            Tags=TAGS,
        )
        print(f"created role {NAME}")
    iam.put_role_policy(RoleName=NAME, PolicyName=NAME, PolicyDocument=json.dumps(policy))
    iam.attach_role_policy(RoleName=NAME, PolicyArn=SSM_CORE_POLICY)
    try:
        iam.get_instance_profile(InstanceProfileName=NAME)
    except iam.exceptions.NoSuchEntityException:
        iam.create_instance_profile(InstanceProfileName=NAME, Tags=TAGS)
        iam.add_role_to_instance_profile(InstanceProfileName=NAME, RoleName=NAME)
        print(f"created instance profile {NAME}")
    return NAME


def ensure_api_key(ssm) -> None:
    try:
        ssm.get_parameter(Name=API_KEY_PARAM)
        print(f"API key: using existing {API_KEY_PARAM}")
    except ssm.exceptions.ParameterNotFound:
        ssm.put_parameter(
            Name=API_KEY_PARAM,
            Type="SecureString",
            Tags=TAGS,
            Value=secrets.token_urlsafe(24),
            Description="X-API-Key for the housing analyst app",
        )
        print(f"API key: created {API_KEY_PARAM} (read it with the command `status` prints)")


def upload_data(s3, data_dir: Path, bucket: str) -> str:
    version = (data_dir / "active_version.txt").read_text().strip()
    src = data_dir / "parquet" / version
    for path in sorted(src.iterdir()):
        key = f"{DATA_PREFIX}/{version}/{path.name}"
        try:
            if s3.head_object(Bucket=bucket, Key=key)["ContentLength"] == path.stat().st_size:
                continue
        except s3.exceptions.ClientError:
            pass
        s3.upload_file(str(path), bucket, key)
        print(f"uploaded s3://{bucket}/{key}")
    return version


def ami_param(arch: str) -> str:
    if arch not in AMI_ARCHES:
        raise ValueError(f"no Amazon Linux 2023 image for architecture {arch!r}")
    return AMI_PARAM.format(arch=AMI_ARCHES[arch])


def instance_arch(ec2, instance_type: str) -> str:
    """The instance type's CPU architecture, so the image matches it (t3 → x86_64, t4g → arm64)."""
    info = ec2.describe_instance_types(InstanceTypes=[instance_type])["InstanceTypes"][0]
    arches = info["ProcessorInfo"]["SupportedArchitectures"]
    return next((a for a in ("x86_64", "arm64") if a in arches), arches[0])


def latest_ami(ssm, ec2, instance_type: str) -> str:
    return ssm.get_parameter(Name=ami_param(instance_arch(ec2, instance_type)))["Parameter"][
        "Value"
    ]


def run_instance(
    ec2, *, ami: str, instance_type: str, group_id: str, profile: str, script: str
) -> dict:
    return ec2.run_instances(
        ImageId=ami,
        InstanceType=instance_type,
        MinCount=1,
        MaxCount=1,
        SecurityGroupIds=[group_id],
        IamInstanceProfile={"Name": profile},
        UserData=script,
        # Hop limit 2: containers sit one network hop behind the host and need the instance
        # role's credentials from the metadata service (IMDSv2 only).
        MetadataOptions={"HttpTokens": "required", "HttpPutResponseHopLimit": 2},
        BlockDeviceMappings=[
            {
                "DeviceName": "/dev/xvda",
                "Ebs": {"VolumeSize": 20, "VolumeType": "gp3", "Encrypted": True},
            }
        ],
        TagSpecifications=[
            {"ResourceType": kind, "Tags": [{"Key": "Name", "Value": NAME}, *TAGS]}
            for kind in ("instance", "volume")
        ],
    )["Instances"][0]


# ---- commands -----------------------------------------------------------------------------------


def clients():
    import boto3

    session = boto3.Session(region_name=REGION)
    names = ("ec2", "iam", "ssm", "s3", "sts", "sagemaker")
    return {n: session.client(n) for n in names}


def error_code(exc: Exception) -> str:
    return getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)


def cmd_check(c, args) -> int:
    """Try each permission `up` needs, without creating anything."""
    account = c["sts"].get_caller_identity()["Account"]
    bucket = args.bucket or default_bucket(account)
    results: list[tuple[str, str, str]] = []  # (label, OK | NO | ??, detail)

    def probe(label: str, fn, ok_codes=("DryRunOperation",)):
        try:
            fn()
            results.append((label, "OK", "ok"))
        except Exception as exc:  # report every probe, don't stop at the first
            code = error_code(exc)
            results.append((label, "OK" if code in ok_codes else "NO", code))

    found: dict[str, str] = {}

    def describe_type():
        found["arch"] = instance_arch(c["ec2"], args.instance_type)

    def read_ami():
        # The read itself tests the SSM permission, so it runs even when the architecture is
        # unknown; but only an image of the right architecture is used for the launch dry run
        # (an x86 image on a t4g type would fail for the wrong reason).
        image = c["ssm"].get_parameter(Name=ami_param(found.get("arch", "x86_64")))
        if "arch" in found:
            found["ami"] = image["Parameter"]["Value"]

    profile = args.instance_profile or (NAME if _profile_exists(c["iam"]) else None)

    probe(
        "S3 write to the data prefix",
        lambda: c["s3"].put_object(Bucket=bucket, Key=f"{DATA_PREFIX}/.write-check", Body=b""),
    )
    probe(
        "SSM read the API key",
        lambda: c["ssm"].get_parameter(Name=API_KEY_PARAM),
        ok_codes=("ParameterNotFound",),
    )
    probe("EC2 describe the instance type", describe_type)
    probe("SSM read the AMI id", read_ami)
    probe(
        "IAM read the app role",
        lambda: c["iam"].get_role(RoleName=NAME),
        ok_codes=("NoSuchEntity",),
    )
    probe("EC2 describe the default VPC", lambda: default_vpc(c["ec2"]))
    probe(
        "EC2 create a security group (dry run)",
        lambda: c["ec2"].create_security_group(
            GroupName=NAME, Description="check", VpcId=default_vpc(c["ec2"]), DryRun=True
        ),
    )
    # With the instance profile, the dry run also checks iam:PassRole on its role, which
    # Studio's SageMaker policy usually grants only for SageMaker roles.
    launch = {"IamInstanceProfile": {"Name": profile}} if profile else {}
    label = (
        "EC2 launch an instance with the app role (dry run)"
        if profile
        else "EC2 launch an instance (dry run, without the role)"
    )
    if "ami" in found:
        probe(
            label,
            lambda: c["ec2"].run_instances(
                ImageId=found["ami"],
                InstanceType=args.instance_type,
                MinCount=1,
                MaxCount=1,
                DryRun=True,
                **launch,
            ),
        )
    else:  # without a matching image the dry run would fail for that reason, not permissions
        why = "no image id" if "arch" in found else "the instance type's architecture is unknown"
        results.append((label, "??", f"not checked: {why} (see the lines above)"))
    probe(
        "SageMaker describe the endpoint",
        lambda: c["sagemaker"].describe_endpoint(EndpointName=args.endpoint),
        ok_codes=("ValidationException",),
    )
    # Writes that have no dry run: AWS only answers them by doing them.
    unchecked = ["SSM create the API key (ssm:PutParameter)"]
    if not profile:
        unchecked += ["IAM create the app role (iam:CreateRole, iam:PutRolePolicy, ...)",
                      "EC2 pass the app role to the instance (iam:PassRole)"]  # fmt: skip
    results += [(label, "??", "not checkable before it exists") for label in unchecked]
    for label, mark, detail in results:
        print(f"{mark}   {label}: {detail}")
    if any(mark == "NO" for _, mark, _ in results):
        print(f"\nSome steps are denied for this role. {CONSOLE_HINT}")
        return 1
    print(
        "\nEverything that can be checked is allowed. Lines marked ?? are tried for real by `up`;"
        f" if `up` stops there, it says which permission is missing. {CONSOLE_HINT} Re-running"
        " `up` after a partial run is safe."
    )
    return 0


CONSOLE_HINT = (
    "See docs/app-deployment.md, 'From the console', for doing those steps in the AWS console."
)


def _profile_exists(iam) -> bool:
    try:
        iam.get_instance_profile(InstanceProfileName=NAME)
        return True
    except Exception:  # missing, or IAM reads denied: either way, don't dry-run with it
        return False


def cmd_up(c, args) -> int:
    cidr = check_cidr(args.allow_cidr)
    existing = find_instance(c["ec2"])
    if existing:
        print(
            f"{NAME} already exists ({existing['InstanceId']}, {existing['State']['Name']}). "
            "Use `status`, `start`, or `down` first."
        )
        return 1
    account = c["sts"].get_caller_identity()["Account"]
    bucket = args.bucket or default_bucket(account)
    version = upload_data(c["s3"], Path(args.data_dir), bucket)
    ensure_api_key(c["ssm"])
    profile = args.instance_profile or ensure_instance_profile(
        c["iam"], instance_policy(account, bucket, args.endpoint)
    )
    group_id = ensure_security_group(c["ec2"], cidr)
    script = user_data(bucket=bucket, dataset_version=version, endpoint=args.endpoint, ref=args.ref)
    for attempt in range(6):  # a new instance profile takes a few seconds to become usable
        try:
            inst = run_instance(
                c["ec2"],
                ami=latest_ami(c["ssm"], c["ec2"], args.instance_type),
                instance_type=args.instance_type,
                group_id=group_id,
                profile=profile,
                script=script,
            )
            break
        except Exception as exc:
            if error_code(exc) != "InvalidParameterValue" or attempt == 5:
                raise
            time.sleep(10)
    print(f"launched {inst['InstanceId']} ({args.instance_type}); waiting until it is running…")
    c["ec2"].get_waiter("instance_running").wait(InstanceIds=[inst["InstanceId"]])
    print("Running. Setup (Docker, build, data) takes about 5 minutes more.")
    return cmd_status(c, args)


def cmd_status(c, args) -> int:
    inst = find_instance(c["ec2"])
    if not inst:
        print(f"No {NAME} instance.")
        return 1
    state = inst["State"]["Name"]
    print(f"{inst['InstanceId']} {inst['InstanceType']} {state}")
    for name, url in app_urls(inst.get("PublicDnsName")).items():
        print(f"  {name}: {url}")
    for group in inst.get("SecurityGroups", []):
        rules = c["ec2"].describe_security_groups(GroupIds=[group["GroupId"]])["SecurityGroups"]
        cidrs = sorted({r["CidrIp"] for p in rules[0]["IpPermissions"] for r in p["IpRanges"]})
        print(f"  allowed from: {', '.join(cidrs) or 'nowhere'}")
    print(
        f"  API key: aws ssm get-parameter --region {REGION} --name {API_KEY_PARAM} "
        "--with-decryption --query Parameter.Value --output text"
    )
    print(f"  setup log: Session Manager shell → sudo tail /var/log/{NAME}-setup.log")
    return 0


def cmd_allow(c, args) -> int:
    group_id = find_security_group(c["ec2"], default_vpc(c["ec2"]))
    if not group_id:
        print(f"No {NAME} security group; run `up`.")
        return 1
    set_ingress(c["ec2"], group_id, check_cidr(args.allow_cidr))
    print(f"{NAME} now allows only {check_cidr(args.allow_cidr)}.")
    return 0


def cmd_stop_start(c, args) -> int:
    inst = find_instance(c["ec2"])
    if not inst:
        print(f"No {NAME} instance.")
        return 1
    iid = inst["InstanceId"]
    if args.command == "stop":
        c["ec2"].stop_instances(InstanceIds=[iid])
        c["ec2"].get_waiter("instance_stopped").wait(InstanceIds=[iid])
        print(f"{iid} stopped (its disk still costs a few cents a day; `down` removes it).")
        return 0
    c["ec2"].start_instances(InstanceIds=[iid])
    c["ec2"].get_waiter("instance_running").wait(InstanceIds=[iid])
    print("Started; the app is back in about a minute. The public address changes on each start:")
    return cmd_status(c, args)


def cmd_down(c, args) -> int:
    ec2, iam = c["ec2"], c["iam"]
    inst = find_instance(ec2)
    if inst:
        ec2.terminate_instances(InstanceIds=[inst["InstanceId"]])
        print(f"terminating {inst['InstanceId']}…")
        ec2.get_waiter("instance_terminated").wait(InstanceIds=[inst["InstanceId"]])
    group_id = find_security_group(ec2, default_vpc(ec2))
    if group_id:
        for attempt in range(12):  # the terminated instance's network interface lingers briefly
            try:
                ec2.delete_security_group(GroupId=group_id)
                break
            except Exception as exc:
                if error_code(exc) != "DependencyViolation" or attempt == 11:
                    raise
                time.sleep(10)
        print(f"deleted security group {group_id}")
    if not args.instance_profile:
        _delete_role(iam)
    try:
        c["ssm"].delete_parameter(Name=API_KEY_PARAM)
        print(f"deleted {API_KEY_PARAM}")
    except c["ssm"].exceptions.ParameterNotFound:
        pass
    print("Done. The dataset copy in S3 is kept (a few cents a month).")
    return 0


def _delete_role(iam) -> None:
    try:
        tags = {t["Key"]: t["Value"] for t in iam.list_role_tags(RoleName=NAME)["Tags"]}
    except iam.exceptions.NoSuchEntityException:
        return
    if tags.get("project") != "llm-final":
        print(f"Role {NAME} wasn't created by this script; leaving it.")
        return
    try:
        iam.remove_role_from_instance_profile(InstanceProfileName=NAME, RoleName=NAME)
        iam.delete_instance_profile(InstanceProfileName=NAME)
    except iam.exceptions.NoSuchEntityException:
        pass
    iam.delete_role_policy(RoleName=NAME, PolicyName=NAME)
    iam.detach_role_policy(RoleName=NAME, PolicyArn=SSM_CORE_POLICY)
    iam.delete_role(RoleName=NAME)
    print(f"deleted role and instance profile {NAME}")


def cmd_policy(c, args) -> int:
    account = c["sts"].get_caller_identity()["Account"]
    bucket = args.bucket or default_bucket(account)
    print(json.dumps(instance_policy(account, bucket, args.endpoint), indent=2))
    return 0


def cmd_user_data(c, args) -> int:
    account = c["sts"].get_caller_identity()["Account"]
    version = (Path(args.data_dir) / "active_version.txt").read_text().strip()
    print(
        user_data(
            bucket=args.bucket or default_bucket(account),
            dataset_version=version,
            endpoint=args.endpoint,
            ref=args.ref,
        ),
        end="",
    )
    return 0


COMMANDS = {
    "check": cmd_check,
    "up": cmd_up,
    "status": cmd_status,
    "allow": cmd_allow,
    "stop": cmd_stop_start,
    "start": cmd_stop_start,
    "down": cmd_down,
    "user-data": cmd_user_data,
    "policy": cmd_policy,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--allow-cidr", help="your public IP as a.b.c.d/32 (up, allow)")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help=f"default: {DEFAULT_ENDPOINT}")
    parser.add_argument("--instance-type", default=DEFAULT_INSTANCE_TYPE)
    parser.add_argument("--ref", default="main", help="git branch, tag, or commit to deploy")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--bucket", help="default: the SageMaker default bucket")
    parser.add_argument(
        "--instance-profile", help="use an existing instance profile (e.g. made in the console)"
    )
    args = parser.parse_args(argv)
    if args.command in ("up", "allow") and not args.allow_cidr:
        parser.error(
            f"{args.command} needs --allow-cidr <your-ip>/32 "
            "(find it with `curl -s https://checkip.amazonaws.com`)"
        )
    try:
        if args.allow_cidr:
            check_cidr(args.allow_cidr)
    except ValueError as exc:
        parser.error(str(exc))
    return COMMANDS[args.command](clients(), args)


if __name__ == "__main__":
    sys.exit(main())
