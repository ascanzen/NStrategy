#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
SERVICES=(n-pattern-service n-pattern-api n-pattern-web)

usage() {
  cat <<'USAGE'
Usage: scripts/deploy_prod.sh <command>

Commands:
  up       Build and start production services
  restart  Restart production services
  down     Stop production services
  status   Show service status
  logs     Follow recent service logs
  health   Check API health endpoint
USAGE
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

load_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    cp "$ROOT_DIR/.env.example" "$ENV_FILE"
    die "Created $ENV_FILE. Please edit it and set TUSHARE_TOKEN before deploying."
  fi

  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a

  if [[ -z "${TUSHARE_TOKEN:-}" || "${TUSHARE_TOKEN:-}" == "replace_with_your_token" ]]; then
    die "TUSHARE_TOKEN is missing in $ENV_FILE."
  fi
}

check_tools() {
  command -v docker >/dev/null 2>&1 || die "Docker is not installed or not in PATH."
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required."
}

compose() {
  docker compose --env-file "$ENV_FILE" "$@"
}

ensure_dirs() {
  mkdir -p "$ROOT_DIR/data" "$ROOT_DIR/outputs" "$ROOT_DIR/logs"
}

health() {
  local port="${API_PORT:-8000}"
  local url="http://127.0.0.1:${port}/api/health"
  command -v curl >/dev/null 2>&1 || die "curl is required for health checks."
  curl -fsS "$url" >/dev/null
  echo "API health check passed: $url"
}

wait_for_health() {
  local attempt
  for attempt in $(seq 1 30); do
    if health >/dev/null 2>&1; then
      health
      return 0
    fi
    sleep 2
  done
  die "API health check did not pass after 60 seconds."
}

main() {
  local command="${1:-}"
  [[ -n "$command" ]] || { usage; exit 1; }

  cd "$ROOT_DIR"
  check_tools

  case "$command" in
    up)
      load_env
      ensure_dirs
      compose up -d --build "${SERVICES[@]}"
      wait_for_health
      compose ps
      ;;
    restart)
      load_env
      compose up -d --build "${SERVICES[@]}"
      wait_for_health
      compose ps
      ;;
    down)
      load_env
      compose down
      ;;
    status)
      load_env
      compose ps
      ;;
    logs)
      load_env
      compose logs -f --tail=200 "${SERVICES[@]}"
      ;;
    health)
      load_env
      health
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

main "$@"
