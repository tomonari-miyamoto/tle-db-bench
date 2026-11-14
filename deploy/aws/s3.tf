data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

resource "aws_s3_bucket" "bench" {
  bucket        = "tle-bench-${data.aws_caller_identity.current.account_id}-${data.aws_region.current.region}"
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "bench" {
  bucket = aws_s3_bucket.bench.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "bench" {
  bucket = aws_s3_bucket.bench.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "bench" {
  bucket                  = aws_s3_bucket.bench.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "bench" {
  bucket = aws_s3_bucket.bench.id

  rule {
    id     = "expire-noncurrent"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  depends_on = [aws_s3_bucket_versioning.bench]
}
