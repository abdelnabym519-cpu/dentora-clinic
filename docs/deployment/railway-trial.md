# Railway hosted 3-day trial

This runbook deploys the merged DentalPin trial from this repository. The client receives only public URLs and credentials; the trial clock stays under deployment control.

## Railway services

Create one Railway project with three services named exactly:

- `Postgres` — Railway managed PostgreSQL.
- `backend` — this GitHub repository, Root Directory `/backend`, Config File `/backend/railway.toml`.
- `frontend` — this GitHub repository, Root Directory `/`, Config File `/railway.frontend.toml`.

The frontend intentionally builds from the repository root because `frontend/Dockerfile.prod` copies `backend/app/modules` into `/module_layers` before the Nuxt production build.

## Ports and domains

Set `PORT=8000` on `backend` and `PORT=3000` on `frontend`, then generate a Railway public domain for both services.

Use the generated frontend domain for browser access. The backend must also have a public domain because browser-side API calls cannot use Railway private networking. Server-side frontend requests can use the backend private domain.

## Backend variables

Set these on `backend`:

```env
PORT=8000
DATABASE_URL=postgresql+asyncpg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}
SECRET_KEY=<64-hex-secret>
BUDGET_PUBLIC_SECRET_KEY=<different-64-hex-secret>
ENVIRONMENT=production
ALLOWED_ORIGINS=https://${{frontend.RAILWAY_PUBLIC_DOMAIN}}
STORAGE_BACKEND=local
STORAGE_LOCAL_PATH=/app/storage
SEED_ON_STARTUP=1
SEED_LANG=en
OPENAI_API_KEY=
TRIAL_MODE=false
TRIAL_STARTED_AT=
TRIAL_DAYS=3
RAILWAY_RUN_UID=0
```

`DATABASE_URL` is constructed with the `postgresql+asyncpg` SQLAlchemy driver required by this backend. Keep the two signing secrets different.

Attach a Railway volume to `backend` mounted at `/app/storage` so uploaded media survives redeploys. `RAILWAY_RUN_UID=0` is required for this trial deployment because Railway mounts the volume as root while the normal DentalPin image runs as a non-root user.

## Frontend variables

Set these on `frontend`:

```env
PORT=3000
NUXT_PUBLIC_API_BASE_URL=https://${{backend.RAILWAY_PUBLIC_DOMAIN}}
API_BASE_URL_SERVER=http://${{backend.RAILWAY_PRIVATE_DOMAIN}}:8000
NUXT_PUBLIC_TRIAL_MODE=false
NUXT_PUBLIC_TRIAL_STARTED_AT=
NUXT_PUBLIC_TRIAL_DAYS=3
NUXT_PUBLIC_DOCS_URL=https://docs.dentalpin.com
```

## Deploy and smoke-test before starting the clock

Deploy both services with trial mode disabled first. Verify:

- backend `/health` returns HTTP 200;
- frontend `/login` loads;
- `admin@demo.clinic` / `demo1234` can sign in;
- patients, schedule, booking and Copilot navigation load;
- media storage is writable.

Do not start the three-day clock until the client is ready to receive the URL.

## Start the client's 3-day clock

At handoff time, generate one UTC timestamp and apply the exact same value to both services:

```env
# backend
TRIAL_MODE=true
TRIAL_STARTED_AT=YYYY-MM-DDTHH:MM:SSZ
TRIAL_DAYS=3

# frontend
NUXT_PUBLIC_TRIAL_MODE=true
NUXT_PUBLIC_TRIAL_STARTED_AT=YYYY-MM-DDTHH:MM:SSZ
NUXT_PUBLIC_TRIAL_DAYS=3
```

Redeploy both services. Confirm the authenticated UI shows the 3-day countdown.

## Expiry acceptance check

After three days the frontend must redirect to `/trial-expired`. Authenticated clinic API operations must be rejected with HTTP 402 and `code=trial_expired`. Trial data remains stored; expiry does not delete clinic data.

## Activate the full version after purchase

Disable the deployment trial and redeploy both services:

```env
TRIAL_MODE=false
NUXT_PUBLIC_TRIAL_MODE=false
```

Do not reset or delete Postgres or the backend storage volume; the same clinic data then continues in the full installation.
