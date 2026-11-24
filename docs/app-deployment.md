# Deployment runbook: the app on EC2

This runbook puts the app (the agent API and the Streamlit UI) on one small EC2 instance in
`us-east-2`. The instance calls the LoRA planner on its SageMaker endpoint. It runs from a
SageMaker Studio terminal, like the other runbooks; `scripts/deploy_app.py` uses Studio's own
`python` and boto3.

```text
 your browser ──:8501──▶ ┌ EC2 t3.small ─────────────────────┐
 curl / clients ─:8000─▶ │ ui (Streamlit) ──HTTP──▶ api (FastAPI)│──▶ SageMaker endpoint
   (your IP only)        │                 DuckDB over /data   │     final-wm-qwen-lora
                         └───────────────────────────────────────┘
```

**What gets created** (all tagged `project=llm-final`, all removed by `down`):

| Resource | Name | Notes |
|---|---|---|
| EC2 instance | `llm-final-app` | `t3.small`, Amazon Linux 2023, 20 GB encrypted gp3, IMDSv2 only |
| Security group | `llm-final-app` | inbound 8501 (UI) and 8000 (API) from one address only |
| IAM role + instance profile | `llm-final-app` | invoke/describe **one** endpoint, read the data prefix, read the API key; Session Manager for a shell |
| SSM parameter | `/llm-final/api-key` | SecureString, random; required as `X-API-Key` by the API |
| S3 objects | `s3://sagemaker-us-east-2-<account>/llm-final/app-data/<version>/` | the Parquet dataset (~40 MB), kept by `down` |

**Cost:** `t3.small` is about $0.02/hour while running (about $0.50/day); stopped, only its disk
costs a few cents a day. The endpoint is billed separately (about $1.5/hour), so the usual rule
still applies: **delete the endpoint after each session**. The app keeps running and shows
"Model endpoint not deployed" until the endpoint is back.

**Security:** the UI and the API are plain HTTP, reachable only from the address you allow. The
API requires the API key; the UI holds it server-side, so anyone who can reach port 8501 can use
the app. Allow only your own address, and stop the instance when you are not using it.

## 0. Before you start

- The code is on `main` (the instance clones the public repo at `--ref`, default `main`).
- `data/` in Studio holds the ingested dataset (`data/active_version.txt` is `23ccd46a4560`).
  If not, run step 2 of [deployment.md](deployment.md).
- Find your public IP from your laptop's browser or terminal: `curl -s https://checkip.amazonaws.com`.
  You will allow `<that-ip>/32`.

## 1. Check permissions (nothing is created)

```bash
cd ~/llm-class-final && git pull
python scripts/deploy_app.py check
```

Each line starts with `OK` (allowed), `NO` (denied), or `??`. A `??` line is a write that AWS can
only answer by doing it: creating the API key and the role, and passing the role to the instance
(`iam:PassRole`; once the role exists, `check` tests it with a dry-run launch). `up` tries those
for real and names the missing permission if one is denied; re-running `up` after that is safe.
If any line says `NO`, or `up` stops at a `??` step, do that step in the console instead; see
[From the console](#from-the-console-if-check-reports-no-or-up-is-denied) below. Studio's SageMaker policy usually
allows `iam:PassRole` only for SageMaker roles, so expect to need the console for at least that.

## 2. Launch (about 2 minutes, then about 5 minutes of setup)

```bash
python scripts/deploy_app.py up --allow-cidr <your-ip>/32
```

It uploads the dataset to S3 (skipped when already there), creates the API key, the role, and the
security group, launches the instance, and prints its URLs. The instance then installs Docker,
clones the repo, copies the data, and runs `docker compose up --build` (log:
`/var/log/llm-final-app-setup.log`). After about 5 minutes:

```bash
python scripts/deploy_app.py status
```

Open the `ui:` URL in your browser. The sidebar status shows the endpoint state.

## 3. Use it with the model

Deploy the LoRA endpoint under the name the app expects (see [training.md](training.md)):

```bash
python scripts/deploy_endpoint.py --name final-wm-qwen-lora \
  --model-data s3://…/output/model.tar.gz --fallback-instance-types ml.g6.2xlarge ml.g6e.xlarge
```

When it is InService, the UI status turns green (it refreshes every 30 seconds). To call the API
directly:

```bash
KEY=$(aws ssm get-parameter --region us-east-2 --name /llm-final/api-key --with-decryption \
  --query Parameter.Value --output text)
curl -s http://<public-dns>:8000/ready
curl -s http://<public-dns>:8000/v1/ask -H "X-API-Key: $KEY" -H 'content-type: application/json' \
  -d '{"question": "Rank Colorado cities by ZHVI growth in 2025", "include_rows": false}'
```

Run `curl` from the allowed address (your laptop); Studio's address is not allowed. Interactive
API docs are at `http://<public-dns>:8000/docs`.

After the session, delete the endpoint as usual:
`python scripts/deploy_endpoint.py --delete --name final-wm-qwen-lora`.

## 4. Day to day

```bash
python scripts/deploy_app.py allow --allow-cidr <new-ip>/32   # your IP changed
python scripts/deploy_app.py stop                             # not demoing
python scripts/deploy_app.py start                            # back in ~1 minute, NEW address
```

The containers restart on boot, so `start` needs nothing else. The public address changes on
every start; `start` and `status` print the new one.

**Deploy new code:** `down`, then `up` again (about 7 minutes). The instance builds from `main`
at first boot. Use `--ref <branch>` to try a branch first.

## 5. Tear down

```bash
python scripts/deploy_app.py down
python scripts/deploy_app.py status   # → "No llm-final-app instance."
```

This terminates the instance and deletes the security group, the role and instance profile, and
the API key. The dataset copy in S3 is kept.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Browser can't connect | Setup still running (wait 5 minutes), or your IP changed (`allow`). |
| UI: "Model endpoint not deployed" or "Creating" | The endpoint is deleted or still starting; deploy it as in step 3. |
| UI: "Model endpoint not allowed for this app's role" | The endpoint name differs from the one in the role's policy (`--endpoint`, default `final-wm-qwen-lora`). |
| UI: "Can't reach the agent API" | The API container is down. Open a shell (EC2 console → Connect → Session Manager), then `cd /opt/llm-final-app && sudo docker compose ps` and `sudo docker compose logs api`. |
| Setup failed | EC2 console → Actions → Monitor and troubleshoot → **Get system log**: the `[llm-final-app]` lines show each step, and `SETUP FAILED … at line N: <command>` names the one that failed. The same is in `/var/log/llm-final-app-setup.log`. After fixing the cause, re-run setup in a Session Manager shell: `sudo rm -rf /opt/llm-final-app && sudo bash /var/lib/cloud/instance/scripts/part-001` (or `down` and `up`). |
| Session Manager: "instance is not connected" | The instance role is missing, or lacks `AmazonSSMManagedInstanceCore`. Attach or fix it (Actions → Security → Modify IAM role), then reboot. |
| API answers 401 | Wrong or missing `X-API-Key`; read it again from SSM as in step 3. |

## From the console (if `check` reports `NO` or `up` is denied)

Do the denied steps in the AWS console (us-east-2), then let the script do the rest.

1. **API key** (if SSM is denied): Systems Manager → Parameter Store → Create parameter. Name
   `/llm-final/api-key`, type SecureString, value: a long random string.
2. **Role** (if IAM is denied): IAM → Roles → Create role → AWS service, EC2. Attach
   `AmazonSSMManagedInstanceCore`, name it `llm-final-app`. Then add an inline policy with the
   JSON printed by `python scripts/deploy_app.py policy`.
   The console creates the instance profile with the same name. If only IAM was denied, run
   `up --allow-cidr <ip>/32 --instance-profile llm-final-app`.
3. **Instance** (if EC2 is denied): first upload the data and save the setup script in Studio:
   `aws s3 cp --recursive data/parquet/23ccd46a4560/ s3://sagemaker-us-east-2-<account>/llm-final/app-data/23ccd46a4560/`
   and `python scripts/deploy_app.py user-data > user-data.sh`. Then EC2 → Launch instance: name
   `llm-final-app`, Amazon Linux 2023, `t3.small`, no key pair, a new security group allowing TCP
   8501 and 8000 from "My IP", 20 GB gp3. Under Advanced details, set the IAM instance profile to
   `llm-final-app`, Metadata version "V2 only", Metadata response hop limit `2` (the containers
   need it to get the role's credentials), and paste `user-data.sh` into User data. Add the tag
   `project=llm-final`. Tear down in the console the same way: terminate the instance, then delete
   the security group, role, and parameter.
