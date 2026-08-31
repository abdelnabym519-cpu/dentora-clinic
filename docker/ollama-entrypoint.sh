#!/bin/sh
# Ollama container entrypoint: start the server, then ensure the Dentora
# clinical model exists (pull the small base + create from the Modelfile).
# Uses the native `ollama` CLI inside the ollama/ollama image — no extra
# tooling, no cloud LLM key. Runs once; subsequent starts are no-ops.
set -eu

OLLAMA_BASE_MODEL="${OLLAMA_BASE_MODEL:-qwen3:1.7b}"
OLLAMA_MODEL="${OLLAMA_MODEL:-dentora-qwen3:1.7b}"
MODELFILE_PATH="${MODELFILE_PATH:-/modelfile/Modelfile.dentora-qwen3}"

echo "[ollama] starting server ..."
ollama serve &
SERVER_PID=$!

echo "[ollama] waiting for API ..."
i=0
until ollama list >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 60 ]; then
    echo "[ollama] ERROR: server did not become ready" >&2
    exit 1
  fi
  sleep 2
done

if ollama list | grep -q "${OLLAMA_MODEL}"; then
  echo "[ollama] ${OLLAMA_MODEL} already present."
else
  echo "[ollama] pulling base model ${OLLAMA_BASE_MODEL} (one-time) ..."
  ollama pull "${OLLAMA_BASE_MODEL}"
  echo "[ollama] creating clinical model ${OLLAMA_MODEL} ..."
  ollama create "${OLLAMA_MODEL}" -f "${MODELFILE_PATH}"
  echo "[ollama] warming model ..."
  ollama run "${OLLAMA_MODEL}" "" >/dev/null 2>&1 || true
fi

echo "[ollama] models:"
ollama list

# Keep the server running in the foreground.
wait "${SERVER_PID}"
