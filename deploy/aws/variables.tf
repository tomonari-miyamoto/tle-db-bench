variable "aws_profile" {
  description = "AWS CLI profile used by the provider."
  type        = string
  default     = "bench"
}

variable "az" {
  description = "Single availability zone for the subnet, instances and volumes."
  type        = string

  validation {
    condition     = startswith(var.az, "ap-northeast-1")
    error_message = "az must be in ap-northeast-1 (for example ap-northeast-1a)."
  }
}

variable "project_tag" {
  description = "Value of the Project tag applied to all resources."
  type        = string
  default     = "tle-db-bench"
}

variable "rung" {
  description = "Ladder rung name (s, m, l) applied as the Rung tag for per-rung cost attribution. Activate Project and Rung as cost allocation tags in Billing once they appear after the first apply (see README, Cost)."
  type        = string

  validation {
    condition     = contains(["s", "m", "l"], var.rung)
    error_message = "rung must be one of s, m, l."
  }
}

variable "db_instance_type" {
  description = "EC2 instance type of the database host (the benchmark rung)."
  type        = string
  default     = "m6in.xlarge"
}

variable "client_instance_type" {
  description = "EC2 instance type of the benchmark client host."
  type        = string
  default     = "m6in.2xlarge"
}

variable "db_volume_gb" {
  description = "Size in GB of the DB host data volume."
  type        = number
  default     = 200
}

variable "client_volume_gb" {
  description = "Size in GB of the client host data volume (Parquet files)."
  type        = number
  default     = 100
}

variable "gp3_iops" {
  description = "Provisioned IOPS of the DB data volume."
  type        = number
  default     = 6000
}

variable "gp3_throughput_mbps" {
  description = "Provisioned throughput in MB/s of the DB data volume."
  type        = number
  default     = 400
}
