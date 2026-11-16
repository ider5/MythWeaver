#!/usr/bin/env bash
# Build local release artifacts for simple self-host (frontend dist + optional images).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODE="${1:-dist}"

case "$MODE" in
  dist)
    echo "==> frontend production build"
    (cd frontend && npm ci && npm run build)
    mkdir -p dist/release
    rm -rf dist/release/web
    cp -R frontend/dist dist/release/web
    echo "Wrote dist/release/web (serve these files and proxy /api to 127.0.0.1:8000)"
    ;;
  docker)
    if ! command -v docker >/dev/null 2>&1; then
      echo "docker not found" >&2
      exit 1
    fi
    if [[ ! -f backend/.env ]]; then
      echo "Note: backend/.env is absent. The UI still starts; copy backend/.env.example and recreate before calling models."
    fi
    echo "==> docker compose config"
    docker compose config >/dev/null
    echo "==> docker compose build"
    docker compose build
    echo "OK. Start with: docker compose up -d --wait"
    echo "Open http://localhost:8080"
    ;;
  *)
    echo "Usage: $0 [dist|docker]" >&2
    exit 2
    ;;
esac
