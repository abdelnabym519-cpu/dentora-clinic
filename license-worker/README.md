# Dentora License Worker

Cloudflare Workers + D1 implementation of the Dentora commercial license service.

This is the production replacement for the local FastAPI/PostgreSQL proof-of-concept in `license-server/`. It preserves the same client contract:

- `POST /v1/activate`
- `POST /v1/refresh`
- `GET /health`
- `GET /v1/public-key`
- `POST /admin/licenses`
- `GET /admin/licenses`
- `POST /admin/licenses/:id/renew`
- `POST /admin/licenses/:id/suspend`
- `POST /admin/licenses/:id/resume`
- `GET /admin/licenses/:id/activations`
- `POST /admin/activations/:id/revoke`

## Security model

- License keys are generated once and stored in D1 only as SHA-256 hashes.
- The Ed25519 private signing key exists only as a Cloudflare Worker secret.
- Client packages contain only the matching public key.
- `X-Admin-Key` protects owner-only management endpoints.
- Each license can limit the number of active installations.
- Signed leases let a clinic continue during a temporary Internet outage until `valid_until`.
- Explicit server rejection (`suspended`, `revoked`, expired) is treated differently from an unavailable server by the Dentora client.

## Files

- `src/index.js` — Worker API.
- `migrations/0001_initial.sql` — D1 schema.
- `wrangler.jsonc` — Worker/D1 bindings and lease policy.
- `.dev.vars.example` — local-development secret names only; never commit real values.

See `docs/technical/licensing/CLOUDFLARE_DEPLOY.md` for production deployment.
