#!/usr/bin/env bash
# SimpleParakeet launcher (native Linux, in-process Sherpa ONNX backend).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

CONFIG_PATH="$ROOT/config.json"
EXAMPLE_PATH="$ROOT/config.example.json"
BIN_DIR="$ROOT/bin"
LOG_DIR="$ROOT/logs"
SETUP_FLAG="$ROOT/.setup-complete"
API_BIN="$BIN_DIR/SimpleParakeet/SimpleParakeet"
FFMPEG_BIN="$BIN_DIR/ffmpeg"
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
  local file="$1" key="$2" default="$3" line
  [[ -f "$file" ]] || { echo "$default"; return; }
  line="$(grep -E "\"${key}\"" "$file" 2>/dev/null | head -n 1 || true)"
  if [[ "$line" =~ :[[:space:]]*\"([^\"]*)\" ]]; then
    echo "${BASH_REMATCH[1]}"
  elif [[ "$line" =~ :[[:space:]]*([0-9]+|true|false) ]]; then
    echo "${BASH_REMATCH[1]}"
  else
    echo "$default"
  fi
}

read_port_prompt() {
  local label="$1" default="$2" raw
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
  local host="$1" api_port="$2" model_choice="$3" model_dir="$4"
  local model_type="$5" threads="$6" lexicon_enabled="$7" lexicon_file="$8"
  {
    echo '{'
    printf '  "host": "%s",\n' "$host"
    printf '  "api_port": %s,\n' "$api_port"
    if [[ -n "$model_dir" && -z "$model_choice" ]]; then
      printf '  "model_dir": "%s",\n' "$model_dir"
      printf '  "model_type": "%s",\n' "$model_type"
    else
      printf '  "model_choice": "%s",\n' "$model_choice"
    fi
    printf '  "onnx_threads": %s,\n' "$threads"
    printf '  "lexicon_enabled": %s,\n' "$lexicon_enabled"
    printf '  "lexicon_file": "%s"\n' "$lexicon_file"
    echo '}'
  } >"$CONFIG_PATH"
}

ensure_config() {
  if [[ ! -f "$CONFIG_PATH" ]]; then
    [[ -f "$EXAMPLE_PATH" ]] || { echo "Missing config.example.json" >&2; exit 1; }
    cp "$EXAMPLE_PATH" "$CONFIG_PATH"
  fi
}

run_setup() {
  [[ -t 0 ]] || {
    echo "Setup needs an interactive terminal." >&2
    echo "Double-click RUN-ME.sh, or run: ./RUN-ME.sh" >&2
    exit 1
  }

  local host api_port model_choice model_dir model_type threads lexicon_enabled lexicon_file
  host="$(json_get "$CONFIG_PATH" host 127.0.0.1)"
  api_port="$(json_get "$CONFIG_PATH" api_port 8210)"
  model_choice="$(json_get "$CONFIG_PATH" model_choice '')"
  model_dir="$(json_get "$CONFIG_PATH" model_dir '')"
  model_type="$(json_get "$CONFIG_PATH" model_type nemo_transducer)"
  threads="$(json_get "$CONFIG_PATH" onnx_threads 4)"
  lexicon_enabled="$(json_get "$CONFIG_PATH" lexicon_enabled true)"
  lexicon_file="$(json_get "$CONFIG_PATH" lexicon_file lexicon.json)"

  echo
  echo "SimpleParakeet setup"
  echo "Press Enter to keep the value in [brackets]."
  echo

  if [[ -n "$model_choice" || -z "$model_dir" ]]; then
    echo "Choose the speech model before download:"
    echo "  1. English - Fast (110M), recommended"
    echo "  2. Multilingual (0.6B), slower"
    [[ "$model_choice" == "multilingual-600m" ]] && default_model=2 || default_model=1
    while true; do
      read -r -p "Model [${default_model}]: " model_in || model_in=""
      [[ -z "${model_in// /}" ]] && model_in="$default_model"
      if [[ "$model_in" == "1" ]]; then model_choice="english-110m"; break; fi
      if [[ "$model_in" == "2" ]]; then model_choice="multilingual-600m"; break; fi
      echo "Enter 1 or 2."
    done
    model_dir=""
  fi

  read -r -p "Listen address [${host}]: " host_in || host_in=""
  [[ -n "${host_in// /}" ]] && host="${host_in// /}"
  api_port="$(read_port_prompt "Whisper API port" "$api_port")"
  while port_in_use "$api_port"; do
    echo "Port ${api_port} is already in use."
    api_port="$(read_port_prompt "Whisper API port" "$api_port")"
  done

  write_config "$host" "$api_port" "$model_choice" "$model_dir" "$model_type" \
    "$threads" "$lexicon_enabled" "$lexicon_file"
  date -Iseconds >"$SETUP_FLAG" 2>/dev/null || date >"$SETUP_FLAG"
  echo
  echo "Saved settings to config.json"
  echo
}

cleanup() {
  if [[ -n "$API_PID" ]] && kill -0 "$API_PID" 2>/dev/null; then
    kill -TERM "$API_PID" 2>/dev/null || true
    sleep 0.4
    kill -KILL "$API_PID" 2>/dev/null || true
  fi
  pkill -f "$ROOT/bin/SimpleParakeet/SimpleParakeet" 2>/dev/null || true
}

wait_api_ready() {
  local host="$1" port="$2" timeout_sec="${3:-300}"
  local url="http://${host}:${port}/health" deadline=$((SECONDS + timeout_sec))
  echo "Starting... (waiting for http://${host}:${port})"
  while (( SECONDS < deadline )); do
    if command -v curl >/dev/null 2>&1; then
      curl -fsS --max-time 2 "$url" >/dev/null 2>&1 && return 0
    elif command -v wget >/dev/null 2>&1; then
      wget -q -T 2 -O /dev/null "$url" 2>/dev/null && return 0
    else
      sleep 3
      return 0
    fi
    sleep 0.4
  done
  return 1
}

show_endpoint() {
  local host="$1" port="$2" endpoint="http://${1}:${2}/v1/audio/transcriptions"
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
}

trap cleanup EXIT INT TERM

echo
echo "SimpleParakeet"
echo

ensure_config
if [[ "$FORCE_SETUP" -eq 1 ]]; then rm -f "$SETUP_FLAG"; fi
if [[ ! -f "$SETUP_FLAG" ]]; then run_setup; fi

mkdir -p "$LOG_DIR"
[[ -f "$API_BIN" ]] || { echo "Missing bin/SimpleParakeet/SimpleParakeet" >&2; exit 1; }
[[ -x "$API_BIN" ]] || chmod +x "$API_BIN"
if [[ -f "$FFMPEG_BIN" && ! -x "$FFMPEG_BIN" ]]; then chmod +x "$FFMPEG_BIN"; fi

HOST="$(json_get "$CONFIG_PATH" host 127.0.0.1)"
API_PORT="$(json_get "$CONFIG_PATH" api_port 8210)"
MODEL_CHOICE="$(json_get "$CONFIG_PATH" model_choice '')"
MODEL_DIR="$(json_get "$CONFIG_PATH" model_dir '')"
MODEL_TYPE="$(json_get "$CONFIG_PATH" model_type nemo_transducer)"
ONNX_THREADS="$(json_get "$CONFIG_PATH" onnx_threads 4)"

port_in_use "$API_PORT" && {
  echo "Port ${API_PORT} is already in use. Close it or run: ./launch.sh --setup" >&2
  exit 1
}

[[ -f "$FFMPEG_BIN" ]] || echo "Note: bin/ffmpeg not found. WAV and PCM still work."
export PARAKEET_ROOT="$ROOT" PARAKEET_ONNX_THREADS="$ONNX_THREADS"
if [[ -n "$MODEL_CHOICE" ]]; then
  export PARAKEET_MODEL_CHOICE="$MODEL_CHOICE"
  unset PARAKEET_MODEL_DIR PARAKEET_MODEL_TYPE
else
  export PARAKEET_MODEL_DIR="$MODEL_DIR" PARAKEET_MODEL_TYPE="$MODEL_TYPE"
  unset PARAKEET_MODEL_CHOICE
fi
export PARAKEET_LEXICON_ENABLED="$(json_get "$CONFIG_PATH" lexicon_enabled true)"
export PARAKEET_LEXICON_FILE="$(json_get "$CONFIG_PATH" lexicon_file lexicon.json)"
export PARAKEET_FFMPEG="$FFMPEG_BIN"
export PATH="${BIN_DIR}${PATH:+:$PATH}"

echo "Starting SimpleParakeet (first launch downloads the verified selected model if needed)..."
(
  cd "$BIN_DIR/SimpleParakeet"
  exec "$API_BIN" --host "$HOST" --port "$API_PORT"
) >"$LOG_DIR/api.out.log" 2>"$LOG_DIR/api.err.log" &
API_PID=$!

if ! wait_api_ready "$HOST" "$API_PORT"; then
  tail -n 20 "$LOG_DIR/api.err.log" 2>/dev/null || true
  echo "API did not become ready." >&2
  exit 1
fi

show_endpoint "$HOST" "$API_PORT"
echo "Keep this terminal open while using speech-to-text."
echo "Press Enter to stop."
read -r _ || true
