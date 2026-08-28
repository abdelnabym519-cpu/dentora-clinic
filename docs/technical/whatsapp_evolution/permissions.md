---
module: whatsapp_evolution
last_verified_commit: 0000000
---

# whatsapp_evolution — permissions

Permissions are namespaced by Dentora's existing module registry. No parallel
RBAC system is introduced.

| Permission | Gates | Endpoints |
|------------|-------|-----------|
| `whatsapp_evolution.settings.read` | View non-secret provider/connection status | `GET /api/v1/whatsapp_evolution/settings` |
| `whatsapp_evolution.settings.write` | Configure encrypted credentials, test connection and configure webhook | `PUT /api/v1/whatsapp_evolution/settings`, `POST /api/v1/whatsapp_evolution/test`, `POST /api/v1/whatsapp_evolution/webhook/configure` |

Default module role mapping is **admin only** (`role_permissions = {"admin":
["*"]}`). Sending patient communications continues to use the existing
`notifications.send` permission at the application use-case boundary; provider
credentials are never exposed to dentist/staff clients.

## Public provider webhook

`POST /api/v1/whatsapp_evolution/webhook/{settings_id}` intentionally has no
Dentora user JWT because Evolution calls it server-to-server. It is protected by:

- per-clinic high-entropy `X-Dentora-Webhook-Token`, encrypted at rest;
- constant-time secret comparison;
- opaque Dentora settings UUID tenant binding;
- payload `instance` equality check against the bound instance;
- exact-payload replay/idempotency receipt;
- provider message-id idempotency for inbound messages;
- clinic-scoped delivery-state lookup;
- route rate limiting.

The route never accepts a frontend-supplied delivery status mutation and never
trusts `clinic_id` from a webhook payload.
