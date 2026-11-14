output "db_private_ip" {
  description = "Private IP of the DB host (use as CH_HOST / PG_HOST on the client)."
  value       = aws_instance.db.private_ip
}

output "db_instance_id" {
  description = "Instance id of the DB host."
  value       = aws_instance.db.id
}

output "client_instance_id" {
  description = "Instance id of the client host."
  value       = aws_instance.client.id
}

output "bucket_name" {
  description = "S3 bucket for code and results."
  value       = aws_s3_bucket.bench.bucket
}

output "az" {
  description = "Availability zone in use."
  value       = var.az
}
