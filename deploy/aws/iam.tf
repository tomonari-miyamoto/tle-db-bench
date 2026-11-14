data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

# DB host: SSM core + read the code archive only.
resource "aws_iam_role" "db" {
  name               = "tle-bench-db"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "db_ssm" {
  role       = aws_iam_role.db.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "db_bucket" {
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.bench.arn]
  }

  statement {
    actions   = ["s3:GetObject"]
    resources = [for p in ["code", "env"] : "${aws_s3_bucket.bench.arn}/${p}/*"]
  }
}

resource "aws_iam_role_policy" "db_bucket" {
  name   = "tle-bench-db-bucket"
  role   = aws_iam_role.db.id
  policy = data.aws_iam_policy_document.db_bucket.json
}

resource "aws_iam_instance_profile" "db" {
  name = "tle-bench-db"
  role = aws_iam_role.db.name
}

# Client host: SSM core + S3 read/write on code, data and results, and the right to
# run the tle-bench-cold-restart SSM document on the DB host (used by cold-restart.sh).
resource "aws_iam_role" "client" {
  name               = "tle-bench-client"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "client_ssm" {
  role       = aws_iam_role.client.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "client_access" {
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.bench.arn]
  }

  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [for p in ["code", "env", "data", "results"] : "${aws_s3_bucket.bench.arn}/${p}/*"]
  }

  statement {
    actions = ["ssm:SendCommand"]
    resources = [
      aws_instance.db.arn,
      aws_ssm_document.cold_restart.arn,
    ]
  }

  statement {
    actions   = ["ssm:GetCommandInvocation"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "client_access" {
  name   = "tle-bench-client-access"
  role   = aws_iam_role.client.id
  policy = data.aws_iam_policy_document.client_access.json
}

resource "aws_iam_instance_profile" "client" {
  name = "tle-bench-client"
  role = aws_iam_role.client.name
}
