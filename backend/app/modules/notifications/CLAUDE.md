# Notifications module

Multi-channel notification **gateway**: our own communications logic
(channel resolution, consent, templates, outbox, logging) with pluggable
adapters that put a rendered message on the wire. Email ships built-in;
WhatsApp arrives via the `whatsapp_kapso` community module (Phase 2).
Heavy subscriber + now a publisher. See ADR 0016.

## Architecture

- `channels/` — the **public contract** vendor modules import:
  `ChannelAdapter` protocol, `OutboundMessage`/`AdapterResult`, `Channel`
  enum, and the idempotent `channel_registry` (pre-loads `EmailAdapter`).
  A vendor module `depends=["notifications"]` and calls
  `channel_registry.register(...)` at import time.
- `gateway.py` — `NotificationGateway.enqueue` (consent gate → channel
  resolution → persist `queued` row → publish) and `dispatch_outbox`
  (the scheduled sender, retry + backoff). **No network in a request.**
- `whatsapp_automation.py` — appointment communication policy for the
  three-message WhatsApp sequence. It never imports a vendor implementation;
  it uses the channel registry + notification service/gateway seams only.
- `service.py` — CRUD for templates/preferences/settings/SMTP + the
  `should_send_notification` consent check. No send path here anymore.
- Tables: `communication_messages` (outbox + audit), `notification_templates`,
  `notification_preferences`, `clinic_notification_settings`,
  `clinic_channel_settings`, `clinic_smtp_settings`.

## WhatsApp appointment automation

For clinics that include `whatsapp` in the ordered `channels` for both
`appointment_confirmation` and `appointment_reminder`, and for patients with
`whatsapp_enabled=true`, the appointment flow is:

1. Immediate `appointment_confirmation` after `appointment.scheduled`.
2. First `appointment_reminder` at the clinic's configured `hours_before`
   (24 hours by default).
3. Final `appointment_reminder` two hours before the appointment.

Both proactive template mappings must be approved by the provider before the
WhatsApp path is eligible. The same approved `appointment_reminder` template is
used for both reminders; context includes `reminder_stage` and
`reminder_hours_before` so named provider variables can distinguish them.

The final reminder is WhatsApp-only. If WhatsApp is not eligible, existing
behavior is preserved: email confirmation plus one email reminder. The scheduler
never emits a second fallback email. Deduplication keys include appointment ID
and start time, making scheduler retries idempotent while allowing a rescheduled
appointment to start a new sequence.

## Public API

Routes mounted at `/api/v1/notifications/` (templates, preferences,
settings, logs).

## Dependencies

`manifest.depends = ["patients", "agenda", "budget", "billing", "catalog"]`.

## Permissions

`notifications.send`,
`notifications.templates.{read,write}`,
`notifications.preferences.{read,write}`,
`notifications.settings.{read,write}`,
`notifications.logs.read`.

## Tools exposed

Agent tool in `tools.py` (wraps `NotificationGateway`, no logic duplicated).

| Tool | Category | Wraps | Permission |
|---|---|---|---|
| `send_notification` | WRITE | `NotificationGateway.enqueue` | `notifications.send` |

Structured params only (cloud-eligible under redaction). Enqueues through
the full consent path — never bypasses `do_not_contact`.

## Events emitted

- `notification.queued` / `notification.sent` / `notification.failed` /
  `notification.delivered` / `notification.reply_received`.
- `email.sent` / `email.failed` — **legacy, dual-published** for
  `channel=email` only, for one release, so `patient_timeline` keeps
  recording email comms until it migrates to the generic events.

## Events consumed

- `patient.created`
- `appointment.scheduled` / `appointment.cancelled`
- `budget.sent` / `budget.accepted`
- `invoice.sent`

## Lifecycle

- `removable=False`. Even when SMTP is disabled, the queue/logs surface
  is depended on by the audit feed.

## Gotchas

- **No outbound network calls during a request.** Sending is queued via
  scheduled jobs so the request transaction can commit before the provider
  attempt.
- **Provider abstraction** lives behind channel adapters. `console` email
  prints to stdout — use it in dev.
- **Templates are i18n-aware** (Spanish UI strings). Never hardcode
  copy in handlers — use a template.
- **Locale resolution order**:
  1. Patient preference (``NotificationPreference.preferred_locale``).
  2. Clinic-wide default (``clinic.settings.communication_language``).
  3. ``DEFAULT_COMMUNICATION_LOCALE`` ("es") if neither is set.
  Encapsulated in ``service.resolve_clinic_communication_locale``.
  The clinic-wide setting is owned by this module — UI lives at
  ``/settings/communications/language`` (registered via
  ``frontend/plugins/settings.client.ts``).
- **Preferences are per-patient + per-event-type.** Honour them before
  enqueueing.
- **WhatsApp proactive messages require explicit opt-in and approved HSMs.**
  A configured adapter alone is never enough to make a patient eligible.

## Related ADRs

- `docs/adr/0001-modular-plugin-architecture.md`
- `docs/adr/0003-event-bus-over-direct-imports.md`
- `docs/adr/0016-notification-gateway-and-pluggable-channels.md`

## CHANGELOG

See `./CHANGELOG.md`.
