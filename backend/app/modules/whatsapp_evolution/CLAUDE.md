# whatsapp_evolution module

Optional WhatsApp delivery for Dentora's notifications gateway via a
**self-hosted Evolution API v2** instance. This module is deliberately the thin
provider wire: encrypted per-clinic connection settings, adapter, provider HTTP
client, authenticated webhook and replay receipts. Consent, routing, outbox,
retry, conversation and delivery audit remain in `notifications`.

Do not add prescription domain logic, patient clinical formatting, AI logic,
Arabic/RTL logic or provider credentials to this module.

## Public API

Routes at `/api/v1/whatsapp_evolution/`:

| Method | Path | Auth |
|---|---|---|
| GET | `/settings` | `whatsapp_evolution.settings.read` |
| PUT | `/settings` | `whatsapp_evolution.settings.write` |
| POST | `/test` | `whatsapp_evolution.settings.write` |
| POST | `/webhook/configure` | `whatsapp_evolution.settings.write` |
| POST | `/webhook/{settings_id}` | **PUBLIC provider callback** — per-clinic secret header |

The settings response exposes only booleans showing whether secrets exist.
Never return the API key or webhook token to a client.

## Dependencies

`manifest.depends = ["notifications", "patients"]`. Provider code may use the
stable notifications channel/gateway seam and patient resolution only. The
notifications module does not import this provider; the adapter registers at
module import and unregisters on uninstall.

## Permissions

- `whatsapp_evolution.settings.read`
- `whatsapp_evolution.settings.write`

The manifest maps these to admin through the existing Dentora RBAC system. Do
not create provider-specific roles or a parallel authorization layer.

## Channel adapter

`EvolutionApiAdapter` delivers `Channel.WHATSAPP` and is selected per clinic
through `ClinicChannelSettings.adapter_name = "whatsapp_evolution"`.
`supports()` requires the clinic settings row to be active **and verified**.
Only Evolution declares `requires_proactive_template = False`; the gateway still
requires patient WhatsApp opt-in before proactive text.

The adapter must return `AdapterResult` rather than raising provider delivery
failures. Mark transient network/provider errors retryable and permanent input,
authorization or configuration errors non-retryable.

## Provider client

`client.py` is the only place that knows Evolution URLs, `apikey`, and provider
payload/response shapes. It currently targets the reviewed Evolution API v2
contract for sendText, sendMedia, connectionState and set webhook.

Provider errors are sanitized. Never include response bodies, API keys, message
text or phone numbers in exceptions/logs.

## Webhook trust boundary

`POST /webhook/{settings_id}` has no Dentora user JWT because Evolution calls it
server-to-server. The route:

1. resolves one active provider binding from the opaque Dentora settings UUID;
2. constant-time verifies `X-Dentora-Webhook-Token` against the encrypted
   per-clinic secret;
3. rejects an Evolution `instance` that differs from the bound instance;
4. atomically claims SHA-256(raw body) once in
   `whatsapp_evolution_webhook_receipts`;
5. applies delivery state only through the clinic-scoped notifications gateway;
6. records individual inbound text through the existing conversation seam.

Never trust a `clinic_id` in provider input and never add a frontend endpoint
that directly sets delivery status.

## Data and migrations

- `whatsapp_evolution_settings`: one encrypted provider binding per clinic.
- `whatsapp_evolution_webhook_receipts`: content-free replay/idempotency hashes.
- Own Alembic branch: `whatsapp_evolution`, initial revision `wae_0001`.

The generic `communication_messages` table remains the outbound queue, delivery
state and communication audit record. Do not introduce a second WhatsApp outbox.

## Secrets and PHI

API keys and webhook tokens are Fernet-encrypted using Dentora's existing
server-side encryption utility. Local Evolution runtime secrets belong only in
ignored `.env.evolution`, never Git.

Do not log patient names, full phone numbers, message/prescription content, raw
webhook bodies, API keys or webhook tokens.

## Local runtime

Evolution is optional and intentionally absent from the primary
`docker-compose.yml`. Development uses `docker-compose.evolution.yml` and an
explicitly reviewed `EVOLUTION_API_IMAGE`; do not replace it with an implicit
`latest` pin.

## Prescription integration boundary

The repository audit for this change found no Prescription/e-Prescription
domain module or prescription PDF generator. Do not invent those inside this
provider. When that clinical module exists, its application use-case may format
a minimal safe message and call `NotificationGateway.enqueue` with a stable
`dedup_key`, `channels=["whatsapp"]`, and `message_kind="text"`.

## Verification rule

Never describe this provider as production verified solely because unit/CI
checks pass. Real verification requires a reviewed Evolution runtime, connected
WhatsApp instance, real send, real delivery webhook, state update, retry/failure
exercise and security validation. Until then report external delivery as not
verified.

## Technical documentation

See `docs/technical/whatsapp_evolution/overview.md` and `permissions.md`.

## CHANGELOG

See `./CHANGELOG.md`.
