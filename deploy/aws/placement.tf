resource "aws_placement_group" "bench" {
  name     = "tle-bench"
  strategy = "cluster"
}
