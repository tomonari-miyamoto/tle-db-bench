# AWS deployment (Terraform)

Two EC2 hosts in one AZ and one cluster placement group in ap-northeast-1: a DB host
(ClickHouse + TimescaleDB via docker compose) and a client host (runs `tlebench`). No SSH;
shell access is through SSM. The DB instance type is the "rung" of the benchmark.

State is local and gitignored (`*.tfstate`, `terraform.tfvars`, `.terraform/`); `.terraform.lock.hcl` is committed.

## Prerequisites

- Terraform >= 1.6, AWS CLI v2, `jq`, and the Session Manager plugin if you want interactive shells.
- AWS profile `bench`: `aws sso login --profile bench` (override with `-var aws_profile=...`), and
  `export AWS_PROFILE=bench` in the shell so ssm.sh and push-code.sh pick it up.
- Quota: at least 48 vCPUs of "Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances"
  (largest rung: 16 + 8 vCPUs, with headroom for resizing).
- Pick an AZ that offers both instance types:

  ```bash
  aws ec2 describe-instance-type-offerings --profile bench --region ap-northeast-1 \
    --location-type availability-zone --filters Name=instance-type,Values=m6in.xlarge,m6in.2xlarge,m6in.4xlarge \
    --query 'InstanceTypeOfferings[].[Location,InstanceType]' --output text | sort
  ```

  Then `cp terraform.tfvars.example terraform.tfvars` and set `az`.

## Commands

```bash
cd deploy/aws
terraform init
terraform apply -var-file=rungs/s.tfvars          # first apply (rung S)
terraform apply -var-file=rungs/m.tfvars          # switch rung: resizes the DB host in place
terraform destroy -var-file=rungs/m.tfvars        # tear everything down
```

Changing the rung is an in-place stop, resize and start of the DB instance: its data volume,
private IP and Docker data survive, but the containers do not come back by themselves (compose
has no restart policy), so repeat step 3 and reload with `load --recreate` so the new rung's
limits apply from a fresh table. A resize inside a cluster placement group can fail with
`InsufficientInstanceCapacity`; retry, or try another AZ. The client data volume (Parquet files)
is a separate EBS volume and is kept across rungs; `terraform destroy` deletes it. Each
`rungs/*.tfvars` has a comment with the `.env` limits for the DB host.

## Per-rung procedure

Set `S=deploy/aws/scripts` from the repo root, plus `DB=$(terraform -chdir=deploy/aws output -raw db_instance_id)`,
`CLIENT=$(terraform -chdir=deploy/aws output -raw client_instance_id)` and
`IP=$(terraform -chdir=deploy/aws output -raw db_private_ip)`.

Bootstrap takes a few minutes after `apply`. Before step 2, wait until both hosts report
`bootstrap done`: `$S/ssm.sh $DB 'grep -q "bootstrap done" /var/log/tlebench-bootstrap.log'`
(same for `$CLIENT`); the command fails until the log line exists.

SSM runs commands as root. Run the benchmark steps as `ubuntu`, e.g.
`$S/ssm.sh $CLIENT 'sudo -u ubuntu -H bash -lc "cd /data/tlebench && uv sync"'`.

Keep passwords out of SSM command text (it is stored in command history and CloudTrail): write the
two `.env` files on the laptop and upload them once per rung, `aws s3 cp client.env
s3://$BUCKET/env/client.env` and `aws s3 cp db.env s3://$BUCKET/env/db.env`; the hosts download
them (step 2 and 3) with `aws s3 cp` and `chmod 600`. Use throwaway passwords.

1. Push code: `$S/push-code.sh` (uploads `git archive HEAD`, so commit first).
2. Client, via `$S/ssm.sh $CLIENT '<command>'`: as the `ubuntu` user, download and unpack
   `s3://$BUCKET/code/tlebench.tar.gz` into `/data/tlebench`, run `uv sync`, and fetch
   `s3://$BUCKET/env/client.env` to `/data/tlebench/.env`. That file holds
   `CH_HOST=$IP`, `PG_HOST=$IP`, `PG_PORT=5432`, passwords,
   `TLEBENCH_DB_INSTANCE=$DB` (the `db_instance_id` output; cold-restart.sh needs it on the client) and
   `COLD_RESTART_CMD="deploy/aws/scripts/cold-restart.sh {service}"`. The client's instance role may
   run commands on the DB host only; no AWS profile is needed there.
3. DB host, via `$S/ssm.sh $DB '<command>'`: unpack the same archive into `/data/tlebench`, fetch
   `s3://$BUCKET/env/db.env` to `/data/tlebench/.env`. That file holds the rung's limits
   (`CPU_LIMIT`, `MEM_LIMIT`, `TS_TUNE_MEMORY`, `TS_TUNE_NUM_CPUS`),
   `PG_PORT=5432` (the security group opens 5432, not compose's default 5433), `BIND_ADDR=0.0.0.0` and passwords. Then `cd /data/tlebench && docker compose up -d --wait`.
4. Generate the Parquet data once (first rung only; it persists on the client data volume):
   `uv run tlebench generate --rows 100000000 --out data/full`.
5. On the client, from `/data/tlebench`: `uv run tlebench load --data data/full --recreate`,
   `uv run tlebench run --data data/full --cold --out results/<rung>.json`, then
   `uv run tlebench report --results results/<rung>.json --out results/<rung>.md`
   (options in the top-level README). `--recreate` is required on every rung after the first.
   A full run with `--cold` takes 2.5 to 3.5 h, longer than an SSM command may live, so put the
   load/run/report commands in a script and start it detached as a transient systemd unit:

   ```bash
   $S/ssm.sh $CLIENT 'systemd-run --collect --unit=tlebench-full-m -p User=ubuntu \
     -p WorkingDirectory=/data/tlebench \
     -p StandardOutput=append:/data/tlebench/results/full-m.log \
     -p StandardError=append:/data/tlebench/results/full-m.log \
     /bin/bash -lc /data/tlebench/results/full-m.sh'
   ```

   Then poll with `$S/ssm.sh $CLIENT 'systemctl is-active tlebench-full-m; tail -3 /data/tlebench/results/full-m.log'`.
   SSM truncates command output at about 24 KB, so read long files with `grep`/`sed`/`tail` on the host.
6. Upload results: `aws s3 cp --recursive results/ s3://$BUCKET/results/<rung>/` (the bucket name is in
   `/etc/tlebench-bucket` on both hosts).

## Cost

Every resource carries `Project` and `Rung` tags (the rung comes from `rungs/*.tfvars`). The keys
show up in the management account under Billing → Cost allocation tags up to 24 h after the first
apply; activate both there as soon as they appear and request a backfill on the same page so the
hours before activation are attributed too. Cost Explorer must be enabled once. After a run (data
lags about 24 h):

```bash
deploy/aws/scripts/cost.sh 2026-11-17 2026-12-01   # end date is exclusive
```

It prints cost by service, by rung and the total for the whole `tle-bench` account (keep the
account dedicated to this benchmark), from Cost Explorer. An `(untagged)` line is expected: tax,
usage before the tags were activated and any resource that did not inherit the provider tags land
there. Credits appear as negative lines. The month-end invoice of the `tle-bench` account is the
authoritative figure.

## Teardown

`terraform destroy -var-file=rungs/<rung>.tfvars`. The bucket has `force_destroy = true`, so fetch
results first (`aws s3 sync s3://$BUCKET/results/ ./results-aws/ --profile bench`). Idle hosts
(CPU < 5% for 4 h) are stopped automatically by CloudWatch alarms, but stopped hosts still pay for
EBS. After an auto-stop, start the instance (`aws ec2 start-instances`) and, on the DB host, run
`docker compose up -d --wait` again before the next step.
