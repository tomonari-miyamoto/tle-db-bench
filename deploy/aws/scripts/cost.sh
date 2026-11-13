#!/usr/bin/env bash
# Print the benchmark account's actual cost for a date range, by service and by Rung tag.
# Usage: cost.sh <start YYYY-MM-DD> <end YYYY-MM-DD>   (end is exclusive)
# Env: AWS_PROFILE (default bench). Cost Explorer data lags about 24 h; the Rung breakdown is
# empty until Project and Rung are activated as cost allocation tags in Billing.
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <start YYYY-MM-DD> <end YYYY-MM-DD>" >&2
  exit 2
fi
for d in "$1" "$2"; do
  if ! [[ "$d" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo "invalid date: $d (expected YYYY-MM-DD)" >&2
    exit 2
  fi
done

start="$1"
end="$2"
AWS_PROFILE="${AWS_PROFILE:-bench}"
export AWS_PROFILE

# Cost Explorer is a global API served from us-east-1.
ce() {
  aws ce get-cost-and-usage --region us-east-1 \
    --time-period "Start=$start,End=$end" --granularity MONTHLY \
    --metrics UnblendedCost "$@"
}

sum_groups() {
  # Flatten group rows across months, sum per key, drop zero rows (keep credits, which are
  # negative), sort descending. Tag groups come back as "Rung$<value>"; an empty value is
  # usage without the tag (tax, untagged resources, usage before the tag was activated).
  jq -r '
    [.ResultsByTime[].Groups[] | {k: (.Keys[0]), v: (.Metrics.UnblendedCost.Amount | tonumber)}]
    | group_by(.k) | map({k: .[0].k, v: (map(.v) | add)})
    | map(select((.v | fabs) > 0.0001)) | sort_by(-.v)[]
    | .k |= (sub("^Rung\\$"; "") | if . == "" then "(untagged)" else . end)
    | "\(.v | . * 100 | round / 100 | tostring)\t\(.k)"'
}

echo "== Cost by service, $start to $end (USD, unblended) =="
ce --group-by Type=DIMENSION,Key=SERVICE --output json | sum_groups

echo
echo "== Cost by Rung tag =="
ce --group-by Type=TAG,Key=Rung --output json | sum_groups

echo
echo "== Total =="
ce --output json | jq -r '[.ResultsByTime[].Total.UnblendedCost.Amount | tonumber] | (add // 0) | . * 100 | round / 100'
