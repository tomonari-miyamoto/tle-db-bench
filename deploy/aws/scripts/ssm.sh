#!/usr/bin/env bash
# Run a shell command on an instance via SSM Run Command and print its output.
# Usage: ssm.sh <instance-id> '<command>'
#        SSM_DOCUMENT=<document> ssm.sh <instance-id> '<parameters-json>'
# Env: SSM_DOCUMENT document name (default AWS-RunShellScript); for any other document the second
# argument is its parameters JSON, passed verbatim to --parameters.
# SSM_TIMEOUT seconds (default 3600). Credentials come from the environment: on the
# laptop `export AWS_PROFILE=bench`; on the client host the instance role is used.
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <instance-id> '<command>'   (or SSM_DOCUMENT=<doc> $0 <instance-id> '<parameters-json>')" >&2
  exit 2
fi

instance_id="$1"
command="$2"
SSM_DOCUMENT="${SSM_DOCUMENT:-AWS-RunShellScript}"
SSM_TIMEOUT="${SSM_TIMEOUT:-3600}"
region="ap-northeast-1"

aws_() { aws --region "$region" "$@"; }

if [ "$SSM_DOCUMENT" = "AWS-RunShellScript" ]; then
  parameters="$(jq -n --arg c "$command" --arg t "$SSM_TIMEOUT" '{commands: [$c], executionTimeout: [$t]}')"
else
  parameters="$command"
fi

command_id="$(aws_ ssm send-command \
  --instance-ids "$instance_id" \
  --document-name "$SSM_DOCUMENT" \
  --parameters "$parameters" \
  --timeout-seconds 30 \
  --query 'Command.CommandId' --output text)"

start=$SECONDS
status="Pending"
while true; do
  if out="$(aws_ ssm get-command-invocation \
    --command-id "$command_id" --instance-id "$instance_id" \
    --query 'Status' --output text 2>&1)"; then
    status="$out"
  elif [[ "$out" == *InvocationDoesNotExist* ]]; then
    status="Pending"
  else
    echo "$out" >&2
    exit 1
  fi
  case "$status" in
    Success | Failed | Cancelled | TimedOut) break ;;
  esac
  if [ $((SECONDS - start)) -ge "$SSM_TIMEOUT" ]; then
    echo "timed out waiting for command $command_id" >&2
    exit 124
  fi
  sleep 3
done

aws_ ssm get-command-invocation --command-id "$command_id" --instance-id "$instance_id" \
  --query 'StandardOutputContent' --output text
aws_ ssm get-command-invocation --command-id "$command_id" --instance-id "$instance_id" \
  --query 'StandardErrorContent' --output text >&2

if [ "$status" != "Success" ]; then
  echo "command $command_id finished with status $status" >&2
  exit 1
fi
