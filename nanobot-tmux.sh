#!/usr/bin/env bash
set -euo pipefail

SESSION_NAME="nanobot"
LOG_DIR="${HOME}/.nanobot/logs"
LOG_FILE="${LOG_DIR}/nanobot.log"
LOG_MAX_MB="${NANOBOT_LOG_MAX_MB:-20}"

usage() {
  cat <<USAGE
Usage: $(basename "$0") <command> [--verbose]

Commands:
  start [--verbose]   Start nanobot gateway in tmux (logs to file)
  stop                Stop tmux session
  restart [--verbose] Restart nanobot gateway
  status              Show tmux session status
  attach              Attach to tmux session
  logs                Tail runtime logs
  truncate            Clear current log file
USAGE
}

require_tmux() {
  if ! command -v tmux >/dev/null 2>&1; then
    echo "Error: tmux not found in PATH" >&2
    exit 1
  fi
}

rotate_log_if_needed() {
  mkdir -p "${LOG_DIR}"
  [[ -f "${LOG_FILE}" ]] || return 0

  local size_bytes max_bytes
  size_bytes=$(wc -c < "${LOG_FILE}" | tr -d '[:space:]')
  max_bytes=$((LOG_MAX_MB * 1024 * 1024))

  if (( size_bytes > max_bytes )); then
    local ts
    ts=$(date +"%Y%m%d-%H%M%S")
    mv "${LOG_FILE}" "${LOG_FILE}.${ts}"
    echo "Rotated log: ${LOG_FILE}.${ts}"
  fi
}

start() {
  require_tmux
  rotate_log_if_needed

  if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
    echo "Session '${SESSION_NAME}' already running"
    exit 0
  fi

  local extra=""
  if [[ "${1:-}" == "--verbose" ]]; then
    extra="--verbose"
  fi

  tmux new-session -d -s "${SESSION_NAME}" \
    "nanobot gateway ${extra} 2>&1 | tee -a '${LOG_FILE}'"

  echo "Started nanobot in tmux session '${SESSION_NAME}'"
  echo "Log file: ${LOG_FILE}"
  if [[ -z "${extra}" ]]; then
    echo "Mode: normal (INFO+, no verbose debug flood)"
  else
    echo "Mode: verbose (includes DEBUG logs)"
  fi
}

stop() {
  require_tmux
  if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
    tmux kill-session -t "${SESSION_NAME}"
    echo "Stopped session '${SESSION_NAME}'"
  else
    echo "Session '${SESSION_NAME}' is not running"
  fi
}

status() {
  require_tmux
  if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
    echo "Session '${SESSION_NAME}' is running"
    tmux list-sessions | grep "^${SESSION_NAME}:" || true
  else
    echo "Session '${SESSION_NAME}' is not running"
  fi
}

attach() {
  require_tmux
  tmux attach -t "${SESSION_NAME}"
}

logs() {
  mkdir -p "${LOG_DIR}"
  touch "${LOG_FILE}"
  tail -f "${LOG_FILE}"
}

truncate_logs() {
  mkdir -p "${LOG_DIR}"
  : > "${LOG_FILE}"
  echo "Truncated ${LOG_FILE}"
}

cmd="${1:-}"
opt="${2:-}"

case "${cmd}" in
  start) start "${opt}" ;;
  stop) stop ;;
  restart) stop || true; start "${opt}" ;;
  status) status ;;
  attach) attach ;;
  logs) logs ;;
  truncate) truncate_logs ;;
  *) usage; exit 1 ;;
esac
