# Dentora Voice overview

Dentora Voice is an optional, removable control surface that leaves the rest of Dentora unchanged. Microphone audio is captured in the browser and sent only to a loopback runtime on the same workstation. The loopback process uses faster-whisper and returns text; Dentora's backend receives transcript text, never audio.

## Flow

`Microphone → 127.0.0.1 faster-whisper → transcript → deterministic intent engine → validation/context resolution → existing ToolRegistry.call() → RBAC/guardrails/validation/audit → existing module tool → validated UI action`

The intent engine has no LLM or cloud fallback. It normalizes Arabic/English text, matches registered patterns and aliases, extracts entities, applies conservative fuzzy matching/confidence, detects ambiguity, and builds sequential execution plans.

## Isolation

The implementation lives in `backend/app/modules/voice/` plus the standalone `tools/dentora_voice_runtime/`. The only shared-core change is an optional `AgentContext.audit_sanitizer` hook, defaulting to `None`; therefore every pre-existing agent surface retains prior behavior. Voice opts into the hook to remove PHI from persisted agent audit payloads.

The module uses the existing `app.overlays` frontend slot and adds only module-local i18n files. It does not change Dentora's global localization/RTL architecture, AI inference code, DevOps, WhatsApp, orthodontics, or ML/RL work.

## Command availability

Patient search/open, CBCT presence/open, 3D display, existing segmentation display, existing nerve display, implant-planner display, and core navigation are connected only where real repository targets exist. `COMPARE_SCANS` and `SHOW_PATHOLOGY` are intentionally reported unavailable because the approved base does not contain corresponding targets.

## Safety

Each registry command declares a risk class (`READ`, `NAVIGATION`, `MUTATION`, `DESTRUCTIVE`). Mutation/destructive commands cannot execute solely because speech confidence is high. Any real destructive tool continues through the existing ToolRegistry guardrail/approval path.

## Local STT

The standalone runtime defaults to faster-whisper `small` multilingual on CPU INT8 and accepts an explicit local model directory. It uses `local_files_only=True` and refuses to download models automatically. GPU is an optional runtime configuration, not a product requirement.

Recordings are temporary only: the runtime writes decoder input to an OS temporary file and removes it before returning. Uvicorn access logging is disabled so request metadata cannot accidentally become a transcript log.
