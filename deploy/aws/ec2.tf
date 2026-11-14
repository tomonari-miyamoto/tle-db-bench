data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

resource "aws_instance" "db" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.db_instance_type
  subnet_id              = aws_subnet.public.id
  placement_group        = aws_placement_group.bench.id
  vpc_security_group_ids = [aws_security_group.db.id]
  iam_instance_profile   = aws_iam_instance_profile.db.name
  ebs_optimized          = true
  monitoring             = false

  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 30
    encrypted   = true
  }

  ebs_block_device {
    device_name           = "/dev/sdf"
    volume_type           = "gp3"
    volume_size           = var.db_volume_gb
    iops                  = var.gp3_iops
    throughput            = var.gp3_throughput_mbps
    encrypted             = true
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/user-data/db.sh.tftpl", {
    bucket = aws_s3_bucket.bench.bucket
  })

  tags = { Name = "tle-bench-db" }

  # A newer Ubuntu image must not replace the host (and its data) on a later apply.
  lifecycle {
    ignore_changes = [ami]
  }
}

resource "aws_instance" "client" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.client_instance_type
  subnet_id              = aws_subnet.public.id
  placement_group        = aws_placement_group.bench.id
  vpc_security_group_ids = [aws_security_group.client.id]
  iam_instance_profile   = aws_iam_instance_profile.client.name
  ebs_optimized          = true
  monitoring             = false

  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 30
    encrypted   = true
  }

  user_data = templatefile("${path.module}/user-data/client.sh.tftpl", {
    bucket    = aws_s3_bucket.bench.bucket
    volume_id = aws_ebs_volume.client_data.id
  })

  tags = { Name = "tle-bench-client" }

  # A newer Ubuntu image must not replace the host (and its data) on a later apply.
  lifecycle {
    ignore_changes = [ami]
  }
}

# Holds the generated Parquet files. It is a separate volume (not an ebs_block_device
# on the instance) so it survives DB instance type changes between rungs.
resource "aws_ebs_volume" "client_data" {
  availability_zone = var.az
  type              = "gp3"
  size              = var.client_volume_gb
  iops              = 3000
  throughput        = 125
  encrypted         = true

  tags = { Name = "tle-bench-client-data" }

  lifecycle {
    prevent_destroy = false
  }
}

resource "aws_volume_attachment" "client_data" {
  device_name                    = "/dev/sdf"
  volume_id                      = aws_ebs_volume.client_data.id
  instance_id                    = aws_instance.client.id
  stop_instance_before_detaching = true
}
