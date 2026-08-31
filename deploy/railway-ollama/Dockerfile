# Self-contained Ollama service for Railway private networking.
# Same image used by docker-compose; only the init is baked in so this
# build context (deploy/railway-ollama) needs no other repo files.
FROM ollama/ollama:latest

# Init script + Modelfile used to build the clinical model on first boot.
COPY ollama-entrypoint.sh /app/ollama-entrypoint.sh
COPY Modelfile.dentora-qwen3 /app/Modelfile.dentora-qwen3
RUN chmod +x /app/ollama-entrypoint.sh

# Model storage lives on the mounted Railway volume (/root/.ollama).
ENV OLLAMA_MODEL=dentora-qwen3:1.7b \
    OLLAMA_BASE_MODEL=qwen3:1.7b \
    MODELFILE_PATH=/app/Modelfile.dentora-qwen3 \
    OLLAMA_HOST=0.0.0.0:11434

EXPOSE 11434
CMD ["sh", "-c", "OLLAMA_HOST=0.0.0.0:11434 /app/ollama-entrypoint.sh"]
