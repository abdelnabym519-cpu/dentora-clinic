# Changelog — whatsapp_evolution module

## Unreleased

- feat: add an optional self-hosted Evolution API v2 WhatsApp provider behind
  Dentora's existing notifications `ChannelAdapter` abstraction.
- feat: add per-clinic encrypted Evolution endpoint/API key/webhook token and
  tenant-selected adapter routing through `ClinicChannelSettings`.
- feat: reuse `communication_messages` for asynchronous outbox delivery,
  bounded retries, provider message IDs and delivered/read state.
- feat: add authenticated, instance-bound, rate-limited webhook handling with
  exact-payload replay receipts and existing inbound conversation handling.
- feat: classify transient provider/network failures separately from permanent
  input/configuration failures so bounded retry stops when appropriate.
- feat: add Evolution v2 client primitives for text, media, connection state
  and webhook configuration without introducing a provider SDK dependency.
- security: keep provider response bodies, API keys, webhook tokens, full phone
  numbers and message/prescription content out of provider errors/logs.
- test: cover client validation, status mapping, adapter results, tenant provider
  selection, patient WhatsApp opt-in, replay handling and forged webhook token.
- docs: add isolated optional local Docker setup and technical/security guide.
- known limitation: the audited Dentora tree has no Prescription/e-Prescription
  domain module or prescription PDF generator to connect to; no parallel
  clinical prescription feature is created inside this provider.
- verification: external WhatsApp send/delivery remains unverified until a
  reviewed Evolution runtime and connected WhatsApp instance are exercised.
