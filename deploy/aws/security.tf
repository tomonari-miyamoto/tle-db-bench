# No SSH anywhere: shell access is via SSM Session Manager / Run Command.
resource "aws_security_group" "client" {
  name        = "tle-bench-client"
  description = "Benchmark client: no ingress, all egress"
  vpc_id      = aws_vpc.bench.id

  tags = { Name = "tle-bench-client" }
}

resource "aws_vpc_security_group_egress_rule" "client_all" {
  security_group_id = aws_security_group.client.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_security_group" "db" {
  name        = "tle-bench-db"
  description = "Benchmark DB host: ClickHouse and PostgreSQL from the client only"
  vpc_id      = aws_vpc.bench.id

  tags = { Name = "tle-bench-db" }
}

resource "aws_vpc_security_group_ingress_rule" "db_clickhouse" {
  security_group_id            = aws_security_group.db.id
  description                  = "ClickHouse HTTP from client"
  ip_protocol                  = "tcp"
  from_port                    = 8123
  to_port                      = 8123
  referenced_security_group_id = aws_security_group.client.id
}

resource "aws_vpc_security_group_ingress_rule" "db_postgres" {
  security_group_id            = aws_security_group.db.id
  description                  = "PostgreSQL from client"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.client.id
}

resource "aws_vpc_security_group_egress_rule" "db_all" {
  security_group_id = aws_security_group.db.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# iperf3 from the client only, to record the wire ceiling for the report.
resource "aws_vpc_security_group_ingress_rule" "db_iperf3" {
  security_group_id            = aws_security_group.db.id
  description                  = "iperf3 from client"
  ip_protocol                  = "tcp"
  from_port                    = 5201
  to_port                      = 5201
  referenced_security_group_id = aws_security_group.client.id
}
