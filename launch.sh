#!/usr/bin/env bash
# SimpleParakeet launcher (Linux native).
# Defaults: API 8210, engine 8211 (override in config.json or with --setup / -Setup)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

CONFIG_PATH="$ROOT/config.json"
EXAMPLE_PATH="$ROOT/config.example.json"
BIN_DIR="$ROOT/bin"
LOG_DIR="$ROOT/logs"
SETUP_FLAG="$ROOT/.setup-complete"

API_BIN="$BIN_DIR/SimpleParakeet/SimpleParakeet"
PK_BIN="$BIN_DIR/parakeet-server"
FFMPEG_BIN="$BIN_DIR/ffmpeg"

PK_PID=""
API_PID=""

FORCE_SETUP=0
for arg in "$@"; do
  case "$arg" in
    --setup|-Setup|/setup) FORCE_SETUP=1 ;;
  esac
done

port_in_use() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -lnt 2>/dev/null | grep -qE ":${port}\\b" && return 0
  fi
  if command -v netstat >/dev/null 2>&1; then
    netstat -lnt 2>/dev/null | grep -qE ":${port}\\b" && return 0
  fi
  return 1
}

json_get() {
  # json_get file key default — flat string/number keys only
  local file="$1" key="$2" default="$3"
  [[ -f "$file" ]] || { echo "$default"; return; }
  local line
  line="$(grep -E "\"${key}\"" "$file" 2>/dev/null | head -n 1 || true)"
  if [[ -z "$line" ]]; then
    echo "$default"
    return
  fi
  if [[ "$line" =~ :[[:space:]]*\"([^\"]*)\" ]]; then
    echo "${BASH_REMATCH[1]}"
  elif [[ "$line" =~ :[[:space:]]*([0-9]+) ]]; then
    echo "${BASH_REMATCH[1]}"
  else
    echo "$default"
  fi
}

read_port_prompt() {
  local label="$1" default="$2" raw n
  while true; do
    read -r -p "${label} [${default}]: " raw || raw=""
    if [[ -z "${raw// /}" ]]; then
      echo "$default"
      return
    fi
    if [[ "$raw" =~ ^[0-9]+$ ]] && (( raw >= 1 && raw <= 65535 )); then
      echo "$raw"
      return
    fi
    echo "Enter a number between 1 and 65535."
  done
}

write_config() {
  local host="$1" api_port="$2" pk_port="$3" device="$4" model="$5"
  cat >"$CONFIG_PATH" <<EOF
{
  "host": "${host}",
  "api_port": ${api_port},
  "parakeet_port": ${pk_port},
  "device": "${device}",
  "model": "${model}"
}
EOF
}

ensure_config() {
  if [[ ! -f "$CONFIG_PATH" ]]; then
    if [[ ! -f "$EXAMPLE_PATH" ]]; then
      echo "Missing config.example.json" >&2
      exit 1
    fi
    cp "$EXAMPLE_PATH" "$CONFIG_PATH"
  fi
}

ensure_first_run() {
  if [[ -f "$SETUP_FLAG" && "$FORCE_SETUP" -eq 0 ]]; then
    return
  fi

  # Without a TTY, `read` gets EOF and would silently accept defaults — refuse.
  if [[ ! -t 0 ]]; then
    echo "Setup needs an interactive terminal." >&2
    echo "Double-click RUN-ME.sh (opens a terminal), or run: ./RUN-ME.sh" >&2
    exit 1
  fi

  echo
  echo "SimpleParakeet setup"
  echo "Press Enter to keep the value in [brackets]."
  echo

  local host api_port pk_port device model
  host="$(json_get "$CONFIG_PATH" host 127.0.0.1)"
  api_port="$(json_get "$CONFIG_PATH" api_port 8210)"
  pk_port="$(json_get "$CONFIG_PATH" parakeet_port 8211)"
  device="$(json_get "$CONFIG_PATH" device cpu)"
  model="$(json_get "$CONFIG_PATH" model models/tdt_ctc-110m-f16.gguf)"

  local host_in
  read -r -p "Listen address [${host}]: " host_in || host_in=""
  if [[ -n "${host_in// /}" ]]; then
    host="${host_in// /}"
  fi

  api_port="$(read_port_prompt "Whisper API port" "$api_port")"
  while port_in_use "$api_port"; do
    echo "Port ${api_port} is already in use."
    api_port="$(read_port_prompt "Whisper API port" "$api_port")"
  done

  pk_port="$(read_port_prompt "Internal engine port" "$pk_port")"
  while [[ "$pk_port" == "$api_port" ]] || port_in_use "$pk_port"; do
    if [[ "$pk_port" == "$api_port" ]]; then
      echo "Internal engine port must be different from the API port."
    else
      echo "Port ${pk_port} is already in use."
    fi
    pk_port="$(read_port_prompt "Internal engine port" "$pk_port")"
  done

  write_config "$host" "$api_port" "$pk_port" "$device" "$model"
  date -Iseconds >"$SETUP_FLAG" 2>/dev/null || date >"$SETUP_FLAG"

  echo
  echo "Saved settings to config.json"
  echo
}

resolve_model_path() {
  local model_rel="$1"
  if [[ -z "$model_rel" ]]; then
    model_rel="models/tdt_ctc-110m-f16.gguf"
  fi
  if [[ "$model_rel" = /* ]]; then
    echo "$model_rel"
  else
    echo "$ROOT/$model_rel"
  fi
}

cleanup() {
  local pid
  for pid in "$API_PID" "$PK_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  sleep 0.4
  for pid in "$API_PID" "$PK_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
  done
  # Fallback if children reparented
  pkill -f "$ROOT/bin/SimpleParakeet/SimpleParakeet" 2>/dev/null || true
  pkill -f "$ROOT/bin/parakeet-server" 2>/dev/null || true
}

wait_api_ready() {
  local host="$1" port="$2" timeout_sec="${3:-90}"
  local url="http://${host}:${port}/health"
  local deadline=$((SECONDS + timeout_sec))
  echo "Starting... (waiting for http://${host}:${port})"
  while (( SECONDS < deadline )); do
    if command -v curl >/dev/null 2>&1; then
      if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
        return 0
      fi
    elif command -v wget >/dev/null 2>&1; then
      if wget -q -T 2 -O /dev/null "$url" 2>/dev/null; then
        return 0
      fi
    else
      # No curl/wget: give processes a few seconds and hope
      sleep 3
      return 0
    fi
    sleep 0.4
  done
  return 1
}

show_log_tail() {
  local path="$1" lines="${2:-20}"
  if [[ -f "$path" ]]; then
    echo "--- ${path} ---"
    tail -n "$lines" "$path" 2>/dev/null || true
  fi
}

show_endpoint() {
  local host="$1" port="$2"
  local endpoint="http://${host}:${port}/v1/audio/transcriptions"
  echo
  echo "============================================================"
  echo " Ready. External Whisper endpoint:"
  echo
  echo " $endpoint"
  echo
  echo " Model: whisper-1"
  echo " API key: any non-empty value"
  echo "============================================================"
  echo
  if command -v wl-copy >/dev/null 2>&1; then
    printf '%s' "$endpoint" | wl-copy 2>/dev/null && echo "Copied to clipboard." || true
  elif command -v xclip >/dev/null 2>&1; then
    printf '%s' "$endpoint" | xclip -selection clipboard 2>/dev/null && echo "Copied to clipboard." || true
  elif command -v xsel >/dev/null 2>&1; then
    printf '%s' "$endpoint" | xsel --clipboard 2>/dev/null && echo "Copied to clipboard." || true
  fi
}

trap cleanup EXIT INT TERM

echo
echo "SimpleParakeet"
echo

if [[ "$FORCE_SETUP" -eq 1 ]]; then
  rm -f "$SETUP_FLAG"
fi

mkdir -p "$LOG_DIR"

if [[ ! -x "$PK_BIN" && -f "$PK_BIN" ]]; then
  chmod +x "$PK_BIN" || true
fi
if [[ ! -x "$API_BIN" && -f "$API_BIN" ]]; then
  chmod +x "$API_BIN" || true
fi
if [[ -f "$FFMPEG_BIN" && ! -x "$FFMPEG_BIN" ]]; then
  chmod +x "$FFMPEG_BIN" || true
fi

if [[ ! -f "$PK_BIN" ]]; then
  echo "Missing bin/parakeet-server" >&2
  exit 1
fi
if [[ ! -f "$API_BIN" ]]; then
  echo "Missing bin/SimpleParakeet/SimpleParakeet" >&2
  exit 1
fi

ensure_config
ensure_first_run

HOST="$(json_get "$CONFIG_PATH" host 127.0.0.1)"
API_PORT="$(json_get "$CONFIG_PATH" api_port 8210)"
PK_PORT="$(json_get "$CONFIG_PATH" parakeet_port 8211)"
DEVICE="$(json_get "$CONFIG_PATH" device cpu)"
MODEL_REL="$(json_get "$CONFIG_PATH" model models/tdt_ctc-110m-f16.gguf)"
MODEL_PATH="$(resolve_model_path "$MODEL_REL")"

if [[ ! -f "$MODEL_PATH" ]]; then
  echo "Missing model file: $MODEL_PATH" >&2
  exit 1
fi

if port_in_use "$API_PORT"; then
  echo "Port ${API_PORT} is already in use. Close whatever is using it, or run: ./launch.sh --setup" >&2
  exit 1
fi
if port_in_use "$PK_PORT"; then
  echo "Port ${PK_PORT} is already in use. Close whatever is using it, or run: ./launch.sh --setup" >&2
  exit 1
fi

if [[ ! -f "$FFMPEG_BIN" ]]; then
  echo "Note: bin/ffmpeg not found. WAV and PCM still work."
fi

# Engine may ship sibling .so files in bin/
export LD_LIBRARY_PATH="${BIN_DIR}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PATH="${BIN_DIR}${PATH:+:$PATH}"
export PARAKEET_DEVICE="$DEVICE"
export PARAKEET_UPSTREAM="http://${HOST}:${PK_PORT}/v1/audio/transcriptions"
export PARAKEET_FFMPEG="$FFMPEG_BIN"

echo "Starting: $PK_BIN --model $MODEL_PATH --host $HOST --port $PK_PORT" >"$LOG_DIR/parakeet.out.log"
: >"$LOG_DIR/parakeet.err.log"
(
  cd "$BIN_DIR"
  exec "$PK_BIN" --model "$MODEL_PATH" --host "$HOST" --port "$PK_PORT"
) >>"$LOG_DIR/parakeet.out.log" 2>>"$LOG_DIR/parakeet.err.log" &
PK_PID=$!

echo "Starting: $API_BIN --host $HOST --port $API_PORT" >"$LOG_DIR/api.out.log"
: >"$LOG_DIR/api.err.log"
(
  cd "$BIN_DIR/SimpleParakeet"
  exec "$API_BIN" --host "$HOST" --port "$API_PORT"
) >>"$LOG_DIR/api.out.log" 2>>"$LOG_DIR/api.err.log" &
API_PID=$!

if ! wait_api_ready "$HOST" "$API_PORT"; then
  echo
  echo "Startup failed. Log tails:"
  show_log_tail "$LOG_DIR/parakeet.err.log"
  show_log_tail "$LOG_DIR/api.err.log"
  echo "API did not become ready." >&2
  exit 1
fi

show_endpoint "$HOST" "$API_PORT"
echo "Keep this terminal open while using speech-to-text."
echo "Press Enter to stop."
read -r _ || true
