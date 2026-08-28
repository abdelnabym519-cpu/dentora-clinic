---
module: whatsapp_evolution
last_verified_commit: 0000000
---

# whatsapp_evolution — overview

Optional WhatsApp delivery provider for Dentora using **Evolution API v2,
self-hosted**. It is a community, installable/removable Infrastructure module;
Dentora can boot and operate without it.

> Self-hosted Evolution API is an integration component and WhatsApp
> connectivity depends on the configured WhatsApp session/provider behavior.
> This module does **not** claim official WhatsApp Cloud API compliance for the
> Baileys transport.

## Architecture

```text
Dentora application use-case
        ↓
notifications.NotificationGateway
        ↓
notifications ChannelAdapter contract
        ↓
EvolutionApiAdapter (whatsapp_evolution)
        ↓
Evolution API v2 REST
        ↓
WhatsApp/Baileys session
```

Provider URLs, authentication headers, request/response payloads and Evolution
webhook shapes are isolated inside `app.modules.whatsapp_evolution`. Domain and
application modules use the existing notifications gateway only.

The generic `communication_messages` table remains the outbox, delivery record
and audit source of truth. No parallel WhatsApp delivery table or queue is
created. The existing scheduled notifications dispatcher provides asynchronous
delivery, row locking, bounded attempts and exponential backoff.

## Multi-tenancy and provider selection

`ClinicChannelSettings` selects the adapter for a clinic/channel. The gateway
now honors that row before the legacy registry fallback, so clinics may select
`whatsapp_kapso` or `whatsapp_evolution` independently.

Evolution configuration is one-to-one with `clinic_id`. A `(base_url,
instance_name)` uniqueness constraint prevents accidentally binding the same
Evolution instance to multiple Dentora clinics. Webhooks resolve the tenant from
an opaque settings UUID owned by Dentora and validate the payload instance name;
a `clinic_id` from provider input is never trusted.

## Data model

### `whatsapp_evolution_settings`

Per-clinic provider binding:

- `base_url`
- `instance_name`
- Fernet-encrypted `api_key_encrypted`
- Fernet-encrypted `webhook_token_encrypted`
- `is_active`, `is_verified`, `connection_state`
- verification and webhook-configuration timestamps

The API returns only `has_api_key` / `has_webhook_token`; secret material is
never returned to the frontend.

### `whatsapp_evolution_webhook_receipts`

Stores a SHA-256 hash of exact webhook bytes plus safe routing metadata. Unique
`(clinic_id, event_hash)` provides atomic duplicate/replay suppression without
storing message content, phone numbers or credentials.

Both tables are on the isolated Alembic branch `whatsapp_evolution`
(`wae_0001`).

## Evolution API v2 contract

The adapter targets the current v2 REST contract reviewed on 2026-08-28:

- `POST /message/sendText/{instanceName}` with `apikey` header.
- `POST /message/sendMedia/{instanceName}` for media/document payloads.
- `GET /instance/connectionState/{instanceName}` for connection health.
- `POST /webhook/set/{instanceName}` with custom headers and explicit events.
- Webhook events consumed: `MESSAGES_UPSERT`, `MESSAGES_UPDATE`,
  `CONNECTION_UPDATE`.

Official references:

- https://docs.evolutionfoundation.com.br/evolution-api/send-text-message
- https://docs.evolutionfoundation.com.br/evolution-api/get-connection-state
- https://docs.evolutionfoundation.com.br/en/evolution-api/set-webhook
- https://github.com/evolution-foundation/evolution-api

### Version/security note

The latest stable source inspected on 2026-08-28 reports **2.3.7**. An open
upstream issue (#2686) reports that stable 2.3.7 embeds Baileys 7.0.0-rc.9,
inside the affected range for CVE-2026-48063, while the development line has a
newer dependency. Therefore `docker-compose.evolution.yml` deliberately does
not default to `latest` or silently pin 2.3.7. Set `EVOLUTION_API_IMAGE` to an
explicit, security-reviewed Evolution API v2 image before use.

- https://github.com/evolution-foundation/evolution-api/issues/2686

## Local setup

Dentora's normal `docker-compose.yml` is unchanged. Evolution is opt-in:

1. Copy `.env.evolution.example` to `.env.evolution`.
2. Set `EVOLUTION_API_IMAGE` to a reviewed v2 image.
3. Generate strong `EVOLUTION_API_KEY` and `EVOLUTION_POSTGRES_PASSWORD` values.
4. Start only the optional stack:

```bash
docker compose --env-file .env.evolution -f docker-compose.evolution.yml up -d
```

The API binds to `127.0.0.1:8080` by default, with isolated PostgreSQL and Redis
volumes. Dentora provider credentials are not read from this env file; each
clinic stores its Evolution endpoint/API key through the RBAC-protected settings
API, encrypted at rest.

## Instance and Dentora configuration

Create/connect the WhatsApp instance using the Evolution API administrative
surface, then in Dentora:

1. `PUT /api/v1/whatsapp_evolution/settings`
2. `POST /api/v1/whatsapp_evolution/test`
3. Only a connection state of `open` marks the clinic provider verified.
4. `POST /api/v1/whatsapp_evolution/webhook/configure` with Dentora's public
   HTTPS base URL. Dentora configures a per-clinic random webhook token as
   `X-Dentora-Webhook-Token`.

Activating Evolution selects `whatsapp_evolution` for that clinic's WhatsApp
channel. Existing Kapso clinics are not globally switched.

## Delivery states and source of truth

The existing `communication_messages` lifecycle is reused:

```text
queued → sending → sent → delivered → read
                 ↘ failed
```

- `sent`: Evolution accepted the send and returned a provider message ID.
- `delivered` / `read` / provider `failed`: mapped from `MESSAGES_UPDATE`.
- `read` is terminal with respect to a later delivered event.
- Unknown/out-of-order events do not create a cross-tenant message.

Evolution commonly acknowledges a send before the final WhatsApp delivery
state. Provider webhooks therefore remain the source of truth for later
delivery/read updates.

## Retry policy

Dentora's existing outbox is bounded by each message's `max_attempts` (default
5) with exponential delays starting at 60 seconds and capped at one hour.

Evolution failures are classified:

- **Transient / retryable:** timeout, transport errors, HTTP 408/425/429 and
  5xx availability failures.
- **Permanent / non-retryable:** invalid destination/input, authorization or
  configuration failures, and other non-transient 4xx responses.

Permanent failures consume the remaining retry budget immediately. There is no
infinite retry.

## Idempotency and replay handling

Outbound application use-cases use the existing
`CommunicationMessage(clinic_id, dedup_key)` uniqueness contract. Repeating the
same logical operation with the same deduplication key is a no-op.

Inbound provider callbacks add two layers:

1. Exact webhook bytes are atomically claimed once through the webhook receipt
   unique constraint.
2. Inbound WhatsApp messages are also deduplicated by provider message ID, and
   delivery state updates are clinic-scoped/idempotent state mutations.

Webhook authentication uses a high-entropy per-clinic static secret header with
constant-time comparison. Production must use HTTPS and should restrict network
access/reverse-proxy ingress where possible. Evolution's webhook contract does
not provide a Dentora-verifiable provider timestamp signature, so do not present
this header scheme as equivalent to a signed timestamped webhook protocol.

## Logging and PHI

The Evolution client deliberately raises sanitized provider errors. It never
copies provider response bodies into persisted errors/logs. Do not log:

- patient names or message/prescription text,
- API keys or webhook tokens,
- full phone numbers,
- raw webhook bodies.

Safe operational metadata is limited to tenant/resource identifiers, provider,
status and timestamps through the existing notification/audit path.

## Media/PDF

The provider client includes a `send_media` primitive matching the Evolution v2
media endpoint. It is intentionally **not wired to a prescription/PDF workflow**
in this change because the audited Dentora repository has no Prescription /
e-Prescription domain module or prescription PDF generator to reuse. Adding a
parallel prescription system inside this provider would violate module
boundaries and the minimal-change requirement.

When a prescription module exists, its application use-case should generate the
safe text/PDF, validate the patient WhatsApp destination and opt-in, then call
`NotificationGateway.enqueue(..., channels=["whatsapp"], message_kind="text",
dedup_key=...)`. The provider must never receive raw domain objects.

## Troubleshooting

- **Provider not selected:** verify the module is installed and
  `ClinicChannelSettings.adapter_name == "whatsapp_evolution"`.
- **No viable channel:** confirm patient phone + WhatsApp opt-in and provider
  `is_active/is_verified`.
- **Test returns not connected:** reconnect the Evolution instance; Dentora only
  treats state `open` as verified.
- **401 webhook:** rotate/reconfigure the per-clinic webhook token.
- **Instance mismatch:** the webhook was sent to the wrong clinic binding;
  verify Evolution instance webhook configuration.
- **Repeated provider event:** exact duplicates are acknowledged and ignored.
- **Message remains sent:** inspect Evolution `MESSAGES_UPDATE` delivery events;
  never fabricate a delivered/read state from the frontend.

## Production requirements / current verification status

Before production approval, require all of the following with a reviewed
Evolution image: live instance connected, real message delivered, real
`MESSAGES_UPDATE` callback processed, retry/failure test, security review,
backup/restore consideration for Evolution's own persistence, HTTPS webhook
exposure, and license/usage-notification compliance with the Evolution API
license in force for the chosen version.

No real Evolution credentials or connected WhatsApp instance are stored in this
repository. Therefore external WhatsApp delivery must be reported as **not
verified** until those live checks are performed.
