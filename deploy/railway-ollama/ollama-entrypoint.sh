#!/bin/sh
# Railway Ollama init: start the server, then ensure the Dentora clinical
# model exists (pull the small qwen3 base + create dentora-qwen3 from the
# bundled Modelfile). Uses the native `ollama` CLI in the ollama/ollama
# image — no extra tooling, no cloud LLM, no API key.
#
# First boot pulls qwen3:1.7b (~1 GB) once into the mounted volume
# (/root/.ollama). Subsequent starts see the model and are fast. The script
# retries the pull/create so a slow first deploy does not strand the service.
set -eu

OLLAMA_BASE_MODEL="${OLLAMA_BASE_MODEL:-qwen3:1.7b}"
OLLAMA_MODEL="${OLLAMA_MODEL:-dentora-qwen3:1.7b}"
MODELFILE_PATH="${MODELFILE_PATH:-/app/Modelfile.dentora-qwen3}"

echo "[ollama] starting server (OLLAMA_HOST=${OLLAMA_HOST:-0.0.0.0:11434}) ..."
ollama serve &
SERVER_PID=$!

echo "[ollama] waiting for API ..."
i=0
until ollama list >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 90 ]; then
    echo "[ollama] ERROR: server did not become ready" >&2
    exit 1
  fi
  sleep 2
done
echo "[ollama] API ready."

if ollama list | grep -q "${OLLAMA_MODEL}"; then
  echo "[ollama] ${OLLAMA_MODEL} already present."
else
  echo "[ollama] pulling base model ${OLLAMA_BASE_MODEL} (one-time; large) ..."
  n=0
  until ollama pull "${OLLAMA_BASE_MODEL}"; do
    n=$((n + 1))
    if [ "$n" -ge 5 ]; then
      echo "[ollama] ERROR: could not pull ${OLLAMA_BASE_MODEL}" >&2
      exit 1
    fi
    echo "[ollama] pull failed; retry $n/5 in 5s ..."
    sleep 5
  done

  echo "[ollama] creating clinical model ${OLLAMA_MODEL} ..."
  ollama create "${OLLAMA_MODEL}" -f "${MODELFILE_PATH}"
fi

echo "[ollama] models:"
ollama list

# Keep the server in the foreground so Railway sees the running process.
wait "${SERVER_PID}"
