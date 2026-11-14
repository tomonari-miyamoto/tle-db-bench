#!/usr/bin/env bash
# Full 100M-row run on rung S, launched detached on the client; progress in results/full-s.log
set -euo pipefail
cd /data/tlebench
export PATH=$HOME/.local/bin:$PATH
log() { echo "[$(date -u +%FT%TZ)] $*"; }
log "generate start"
uv run tlebench generate --rows 100000000 --out data/full
log "generate done"
log "load start"
uv run tlebench load --data data/full --recreate
log "load done"
log "run start"
uv run tlebench run --data data/full --cold --out results/full-s.json
log "run done"
uv run tlebench report --results results/full-s.json --out results/full-s.md
log "ALL DONE"
