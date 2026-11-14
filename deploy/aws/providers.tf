provider "aws" {
  region  = "ap-northeast-1"
  profile = var.aws_profile

  default_tags {
    tags = {
      Project = var.project_tag
      Rung    = var.rung
    }
  }
}
