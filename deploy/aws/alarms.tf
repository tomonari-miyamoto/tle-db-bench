# Stop idle instances after 4 h (48 x 5 min) below 5% CPU to cap cost. A stopped DB host comes
# back without its containers (compose has no restart policy): start it and run
# `docker compose up -d --wait` again before the next load/run.
resource "aws_cloudwatch_metric_alarm" "db_idle" {
  alarm_name          = "tle-bench-db-idle"
  alarm_description   = "Stop the DB host after 4 h of CPU below 5%"
  namespace           = "AWS/EC2"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 48
  threshold           = 5
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = ["arn:aws:automate:${data.aws_region.current.region}:ec2:stop"]

  dimensions = {
    InstanceId = aws_instance.db.id
  }
}

resource "aws_cloudwatch_metric_alarm" "client_idle" {
  alarm_name          = "tle-bench-client-idle"
  alarm_description   = "Stop the client host after 4 h of CPU below 5%"
  namespace           = "AWS/EC2"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 48
  threshold           = 5
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = ["arn:aws:automate:${data.aws_region.current.region}:ec2:stop"]

  dimensions = {
    InstanceId = aws_instance.client.id
  }
}
