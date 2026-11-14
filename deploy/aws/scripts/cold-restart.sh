#!/usr/bin/env bash
# Restart a DB container on the DB host and drop the OS page cache.
# Usage: cold-restart.sh clickhouse|timescaledb
# Env: TLEBENCH_DB_INSTANCE is the DB instance id (required on the client; on a machine
# with terraform it falls back to `terraform output`).
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 clickhouse|timescaledb" >&2
  exit 2
fi

service="$1"
case "$service" in
  clickhouse | timescaledb) ;;
  *)
    echo "invalid service: $service (expected clickhouse or timescaledb)" >&2
    exit 2
    ;;
esac

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -z "${TLEBENCH_DB_INSTANCE:-}" ]; then
  if command -v terraform >/dev/null 2>&1; then
    TLEBENCH_DB_INSTANCE="$(cd "$here/.." && terraform output -raw db_instance_id)"
  else
    echo "TLEBENCH_DB_INSTANCE is not set and terraform is not on PATH" >&2
    echo "set TLEBENCH_DB_INSTANCE=<db_instance_id output> (in .env on the client)" >&2
    exit 2
  fi
  export TLEBENCH_DB_INSTANCE
fi

# The document name must match aws_ssm_document.cold_restart in deploy/aws/ssm.tf.
SSM_DOCUMENT=tle-bench-cold-restart exec "$here/ssm.sh" "$TLEBENCH_DB_INSTANCE" \
  "$(jq -n --arg s "$service" '{service: [$s]}')"
