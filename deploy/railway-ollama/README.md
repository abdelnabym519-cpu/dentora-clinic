# Dentora on Railway — production with real local AI (Ollama)

This is the production runbook for running Dentora end-to-end on Railway
with a **fully-local LLM** (no cloud LLM, no API key).

## Architecture

Four services in ONE Railway project:

| Service   | Source / config                                   | Public? | Purpose                         |
|-----------|---------------------------------------------------|---------|---------------------------------|
| `Postgres`| Railway managed PostgreSQL                        | no      | database                        |
| `ollama`  | this repo, Root Dir `deploy/railway-ollama`       | **no**  | local LLM (private network)     |
| `backend` | this repo, Root Dir `/backend`, config `backend/railway.toml` | yes (domain) | API + migrations + seed |
| `frontend`| this repo, Root Dir `/`, config `railway.frontend.toml`      | yes (domain) | Nuxt UI                |

The `ollama` service runs `ollama/ollama`, pulls `qwen3:1.7b` once into a
volume, and builds the clinical model `dentora-qwen3:1.7b`. It is **never**
given a public domain. The backend reaches it over Railway private
networking at `http://ollama.railway.internal:11434`.

> `localhost` / `host.docker.internal` DO NOT work in production — they point
> at each container itself. Use the Railway private domain above.

## One-time setup in the Railway dashboard

1. Create a project, add the **PostgreSQL** plugin.
2. Add service **backend** → GitHub repo → Root Directory `backend`, Config
   File `backend/railway.toml`. Attach a **Volume** at `/app/storage`.
3. Add service **frontend** → GitHub repo → Root Directory `/`, Config File
   `railway.frontend.toml`.
4. Add service **ollama** → GitHub repo → Root Directory
   `deploy/railway-ollama`, Config File `deploy/railway-ollama/railway.toml`.
   Attach a **Volume** at `/root/.ollama` (this holds the pulled model).
   Recommend >= ~4 GB RAM instance. Do **not** generate a public domain.

Redeploy order: `ollama` first (wait for "models:" log + dentora-qwen3:1.7b),
then `backend`, then `frontend`.

## Backend variables (set on the `backend` service)

```env
PORT=8000
ENVIRONMENT=production
SECRET_KEY=<openssl rand -hex 32>
BUDGET_PUBLIC_SECRET_KEY=<different openssl rand -hex 32>
DATABASE_URL=postgresql+asyncpg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}
ALLOWED_ORIGINS=https://${{frontend.RAILWAY_PUBLIC_DOMAIN}}
STORAGE_BACKEND=local
STORAGE_LOCAL_PATH=/app/storage
SEED_ON_STARTUP=1
SEED_LANG=en
RAILWAY_RUN_UID=0

# --- AI: fully-local Ollama over Railway private networking ---
COPILOT_PROVIDER_DEFAULT=ollama
OLLAMA_BASE_URL=http://ollama.railway.internal:11434
OLLAMA_MODEL=dentora-qwen3:1.7b
COPILOT_MODEL_CHAT_OLLAMA=dentora-qwen3:1.7b
# Qwen3 thinks by default; we want direct JSON answers (provider default off).
OLLAMA_THINK=false
# keep cloud provider unused
OPENAI_API_KEY=
```

## Frontend variables (set on the `frontend` service)

```env
PORT=3000
NUXT_PUBLIC_API_BASE_URL=https://${{backend.RAILWAY_PUBLIC_DOMAIN}}
API_BASE_URL_SERVER=http://${{backend.RAILWAY_PRIVATE_DOMAIN}}:8000
```

## Post-deploy verification

- `ollama` logs show `[ollama] models:` with `dentora-qwen3:1.7b`.
- `https://<backend>/health` and `/health/ready` → 200.
- `https://<frontend>/login` loads; sign in `admin@demo.clinic` / `demo1234`.
- From a patient record, each AI feature (Case Summary, Clinical Report,
  Second Review, Treatment Suggestions, Case Intelligence) and the Clinical
  Copilot return real generated text with `generated_by=ai` and
  `model=dentora-qwen3:1.7b`.

## Alternative: use an external Ollama host

If you run Ollama on your own reachable server (with a public or tunneled
HTTPS endpoint), skip the `ollama` service and set on the backend:

```env
COPILOT_PROVIDER_DEFAULT=ollama
OLLAMA_BASE_URL=https://your-ollama-host
OLLAMA_MODEL=dentora-qwen3:1.7b
```

That server must expose Ollama and already have `dentora-qwen3:1.7b`
(`ollama pull qwen3:1.7b && ollama create dentora-qwen3:1.7b -f
Modelfile.dentora-qwen3`). Do not put `host.docker.internal`/`localhost` here.
