#!/usr/bin/env bash
set -euo pipefail; cd /data/tlebench; export PATH=$HOME/.local/bin:$PATH
log() { echo "[$(date -u +%FT%TZ)] $*"; }
log "load start"; uv run tlebench load --data data/full --recreate; log "load done"
log "run start"; uv run tlebench run --data data/full --cold --out results/full-m.json; log "run done"
uv run tlebench report --results results/full-m.json --out results/full-m.md; log "ALL DONE"
