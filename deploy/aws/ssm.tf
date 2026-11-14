# The only command the client role may run on the DB host (see iam.tf). The name must match
# SSM_DOCUMENT in scripts/cold-restart.sh.
resource "aws_ssm_document" "cold_restart" {
  name            = "tle-bench-cold-restart"
  document_type   = "Command"
  document_format = "YAML"

  content = <<-EOT
    schemaVersion: "2.2"
    description: Restart one benchmark database container and drop the OS page cache.
    parameters:
      service:
        type: String
        description: Compose service to restart.
        # SSM substitutes {{ service }} into the shell line as plain text, so the allow-list is
        # the only guard: never add a value with whitespace or shell metacharacters.
        allowedValues:
          - clickhouse
          - timescaledb
        allowedPattern: "^(clickhouse|timescaledb)$"
    mainSteps:
      - action: aws:runShellScript
        name: coldRestart
        inputs:
          timeoutSeconds: 600
          runCommand:
            - cd /data/tlebench && docker compose restart {{ service }} && sync && echo 3 > /proc/sys/vm/drop_caches
  EOT
}
