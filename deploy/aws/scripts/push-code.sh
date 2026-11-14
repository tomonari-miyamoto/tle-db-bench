#!/usr/bin/env bash
# Upload the current HEAD of the repo to s3://<bucket>/code/tlebench.tar.gz.
set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-bench}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$here/../../.." && pwd)"

BUCKET="$(cd "$repo_root/deploy/aws" && terraform output -raw bucket_name)"

cd "$repo_root"
git archive --format=tar HEAD | gzip |
  aws s3 cp - "s3://$BUCKET/code/tlebench.tar.gz" --profile "$AWS_PROFILE"
echo "uploaded s3://$BUCKET/code/tlebench.tar.gz"
