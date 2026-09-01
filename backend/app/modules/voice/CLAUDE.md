# voice module

Dentora Voice is an isolated local/offline control surface for Dentora.
It converts an already-local transcript into deterministic commands and executes real domain reads/actions only through the existing Agent `ToolRegistry` chokepoint.

## Boundaries

- The backend never receives microphone audio; audio is sent only to the loopback faster-whisper runtime.
- No cloud speech service or LLM is used for voice intent recognition.
- Voice never imports patient, dental_3d, billing, agenda, or report services directly.
- Existing AI inference/model logic is not changed or reimplemented.
- Unsupported integrations are reported as unavailable; they are never faked.

## Public API

Routes mount at `/api/v1/voice/`:
- `POST /voice/interpret` — deterministic transcript-to-plan parsing.
- `POST /voice/execute` — parse then execute a validated sequential plan through ToolRegistry.
Both require `voice.use`.

## Command execution

Every real data/UI command is executed via `ToolRegistry.call()` so RBAC, guardrails, Pydantic validation, and agent audit remain the enforcement path.
Patient resolution uses `patients.search_patients`; dental viewer commands use `dental_3d.get_patient_scene`; Voice owns only a small `voice.ui_action` tool that returns validated frontend actions.
Sequential commands stop on the first failed/ambiguous/unavailable step.

## Privacy

Voice supplies `sanitize_audit_payload` through the optional `AgentContext.audit_sanitizer` hook. This prevents transcript-derived patient names/contact fields and identifiers from being persisted in agent audit payloads. Existing agent surfaces keep their historical behavior because the hook defaults to `None`.
No transcript is persisted by this module and recordings are not stored.

## Permissions

- `voice.use` — use the voice control surface.
Underlying module permissions are re-checked independently by each called ToolRegistry tool.

## Tools exposed

| Tool | Category | Permission | Purpose |
|---|---|---|---|
| `ui_action` | READ | `voice.use` | Return a validated frontend navigation/view action. |

## Frontend

The module mounts `VoiceMount.vue` into the existing `app.overlays` slot. It does not modify the host layout or localization architecture. Voice translations live only under this module layer.

## Local runtime

`tools/dentora_voice_runtime/` runs faster-whisper on `127.0.0.1:8765`. Default execution is CPU INT8. The runtime requires a pre-provisioned local model and refuses automatic model download.

## Known unavailable commands on the approved base

- `COMPARE_SCANS` — no repository scan-comparison target exists.
- `SHOW_PATHOLOGY` — no pathology viewer target exists.
These remain explicit unavailable registry entries until a real feature is independently present.

## Events

Voice emits and consumes no event-bus events.

## Gotchas

Do not route Voice around ToolRegistry to make a command easier. Do not add cloud fallback. Do not log transcript text. Viewer commands must fail if their actual target/result is absent rather than claiming success.
