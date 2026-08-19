# Deploy DentalPin License Service to Cloudflare Workers + D1

This is the production deployment path for the commercial DentalPin license service.

## 1. Install dependencies and authenticate

From Git Bash:

```bash
cd ~/Downloads/dentalpin-license-work/license-worker
npm install
npx wrangler login --use-keyring
```

Complete the Cloudflare browser login once.

## 2. Create the D1 database

```bash
npx wrangler d1 create dentalpin-license --location eeur
```

Copy the returned `database_id` into `wrangler.jsonc`, replacing:

```text
REPLACE_WITH_D1_DATABASE_ID
```

The Worker binding name must remain `DB`.

## 3. Apply D1 migrations

```bash
npx wrangler d1 migrations apply dentalpin-license --remote
```

Confirm the migration when Wrangler asks.

## 4. Prepare production secrets locally

Reuse the Ed25519 key pair already generated under the repository root `.license-dev/`. Never generate a second production private key accidentally after client packages have been released.

```bash
cd ~/Downloads/dentalpin-license-work/license-worker

ADMIN_KEY="$(openssl rand -hex 32)"
PRIVATE_B64="$(openssl base64 -A -in ../.license-dev/private.pem)"
PUBLIC_B64="$(openssl base64 -A -in ../.license-dev/public.pem)"

cat > .secrets.production <<EOF
LICENSE_ADMIN_API_KEY=$ADMIN_KEY
LICENSE_SIGNING_PRIVATE_KEY_B64=$PRIVATE_B64
LICENSE_PUBLIC_KEY_B64=$PUBLIC_B64
EOF

chmod 600 .secrets.production
```

`.secrets.production` is ignored by Git and must never be sent to a client.

## 5. Deploy Worker and secrets together

```bash
npx wrangler deploy --secrets-file .secrets.production
```

Wrangler prints the deployed `workers.dev` URL. Save it in the current shell, for example:

```bash
export DENTALPIN_LICENSE_SERVER_URL="https://dentalpin-license.<your-subdomain>.workers.dev"
```

Do not guess the URL; use the exact URL returned by Wrangler.

## 6. Verify health and public key

```bash
curl -s "$DENTALPIN_LICENSE_SERVER_URL/health" | python -m json.tool
curl -s "$DENTALPIN_LICENSE_SERVER_URL/v1/public-key" | python -m json.tool
```

Expected health response:

```json
{
  "status": "healthy",
  "service": "dentalpin-license"
}
```

## 7. Create a production test license

Keep the admin key out of terminal output and screenshots.

```bash
curl -sS -X POST \
  "$DENTALPIN_LICENSE_SERVER_URL/admin/licenses" \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_name":"Cloudflare Integration Test",
    "plan":"standard",
    "duration_days":30,
    "max_activations":1,
    "features":["core","booking"]
  }' \
  > ../.license-dev/cloudflare-test-license.json

python - <<'PY'
import json
p = "../.license-dev/cloudflare-test-license.json"
d = json.load(open(p, encoding="utf-8"))
for k, v in d.items():
    print(f"{k}: {'[HIDDEN]' if k == 'license_key' else v}")
PY
```

## 8. Build a commercial client package pinned to Cloudflare

```bash
cd ~/Downloads/dentalpin-license-work

export DENTALPIN_LICENSE_PUBLIC_KEY_B64="$(openssl base64 -A -in .license-dev/public.pem)"

bash PREPARE_CLIENT_PACKAGE.sh HEAD
```

The package builder injects only:

- `DENTALPIN_LICENSE_SERVER_URL`
- the Ed25519 public key

It explicitly removes `license-server/`, `license-worker/`, and `.license-dev/` from the client package.

## 9. End-to-end production smoke test

Use the newly generated `DentalPin_Generic_Client.zip` in a clean folder and verify:

1. Without a license, `/setup` returns HTTP 402 and the UI redirects to `/activate`.
2. A valid key activates one installation.
3. The same one-device key is rejected on another installation.
4. Stop/start preserves the activation.
5. Owner `suspend` + client refresh blocks the clinic.
6. Owner `resume` + client refresh restores the same clinic without deleting data.

## Secret handling rules

- Never commit `.secrets.production`.
- Never send `.license-dev/private.pem` to a client.
- Never put `LICENSE_ADMIN_API_KEY` in the client package.
- Back up the Ed25519 private key securely offline. Losing it prevents issuing leases compatible with already released client public keys.
- If the private key is compromised, rotate both server keys and client public keys through a controlled upgrade.
