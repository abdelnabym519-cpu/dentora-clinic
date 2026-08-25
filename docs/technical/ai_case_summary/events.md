# AI Case Summary — events

AI Case Summary v1 emits no event-bus events.

The persisted summary contract and API are the integration surface for downstream stages. This keeps advisory clinical text out of shared event payloads while provenance and dentist-review metadata remain stored with the summary record.
