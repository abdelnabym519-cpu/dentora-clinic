# Dentora Voice — Windows local validation runbook

This directory contains validation tooling only. It does not add Voice features or change the clinical AI stack.

Hardware/microphone validation is **not** considered complete until these commands are run on the target workstation and their real outputs are reviewed.

## 1. Required branch

From the repository root:

```powershell
git checkout feat/dentora-voice
git status
git rev-parse HEAD
```

Do not merge this branch into `main` during Voice validation.

## 2. Voice-only runtime dependencies

The local STT runtime uses a dedicated virtual environment and these dependencies only:

- `faster-whisper>=1.1,<2`
- `fastapi>=0.109`
- `uvicorn[standard]>=0.27`
- `python-multipart>=0.0.6`
- `psutil>=5.9`

Install them on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File tools/dentora_voice_runtime/install.ps1
```

This installer does **not** download a Whisper model.

## 3. Local model placement

Provide two already-downloaded, local CTranslate2 faster-whisper model directories:

```text
models/
  faster-whisper-small/
    model.bin
    config.json
    tokenizer.json
    ...
  faster-whisper-base/
    model.bin
    config.json
    tokenizer.json
    ...
```

The scripts require local model directories and reject a missing `model.bin`. Do not pass a Hugging Face model ID or cloud URL.

Default production-validation runtime model:

```text
models/faster-whisper-small
```

Benchmark comparison model:

```text
models/faster-whisper-base
```

The actual model directory size is measured from the files on your machine by `benchmark.py`; do not substitute an estimated size.

## 4. Offline configuration verification

Run before starting the runtime:

```powershell
powershell -ExecutionPolicy Bypass -File tools/dentora_voice_runtime/verify-offline.ps1
```

Expected output includes:

```text
PASS: runtime binds to 127.0.0.1
PASS: model loading uses local_files_only=True
PASS: default device is CPU
PASS: default compute type is INT8
PASS: no known cloud speech SDK dependency/reference found ...
```

`server.py` intentionally uses `local_files_only=True`, binds to `127.0.0.1`, disables Uvicorn access logging, and deletes its temporary decoder audio file before returning the response.

## 5. Start the local Voice Runtime

Open PowerShell terminal A:

```powershell
powershell -ExecutionPolicy Bypass -File tools/dentora_voice_runtime/run-runtime.ps1 -ModelPath models/faster-whisper-small
```

Expected runtime:

```text
http://127.0.0.1:8765
```

Health check from another terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
```

Expected properties include `engine=faster-whisper`, `device=cpu`, and `compute_type=int8`.

## 6. Hardware benchmark — base + small, CPU INT8

Use only synthetic/non-PHI audio. Never use real patient recordings for validation artifacts.

Example files:

```text
validation-audio/ar-01.wav
validation-audio/en-01.wav
validation-audio/mixed-01.wav
```

Run:

```powershell
powershell -ExecutionPolicy Bypass -File tools/dentora_voice_runtime/run-benchmark.ps1 `
  -BaseModel models/faster-whisper-base `
  -SmallModel models/faster-whisper-small `
  -Sample validation-audio/ar-01.wav,validation-audio/en-01.wav,validation-audio/mixed-01.wav `
  -Output dentora-voice-benchmark.json
```

The JSON output records only aggregate/non-PHI metrics:

- CPU identity and physical/logical core count
- total system RAM
- actual model directory size
- model load time
- warm-up time
- warm transcription latency
- peak process RSS
- average/peak process CPU percentage
- audio duration
- real-time factor (RTF)

The report does **not** write transcript text, audio bytes, source filenames, patient names, phones, emails, or IDs.

## 7. Start Dentora for real microphone E2E

The browser path already implemented by Dentora Voice is:

```text
Microphone -> MediaRecorder -> 127.0.0.1:8765/transcribe
-> faster-whisper -> Transcript -> /voice/execute
-> deterministic Intent -> ToolRegistry -> Dentora UI action
```

### Terminal B — backend/database

From repo root, with a local `.env` or environment variables that satisfy Docker Compose:

```powershell
$env:POSTGRES_PASSWORD="YOUR_LOCAL_TEST_PASSWORD"
$env:SECRET_KEY="dentora-voice-local-validation-secret"
docker compose up -d db backend
```

Backend health:

```powershell
Invoke-RestMethod http://127.0.0.1:8100/health
```

### Terminal C — host Nuxt UI on port 3000

Install existing frontend dependencies once if needed:

```powershell
cd frontend
npm install
cd ..
```

Then:

```powershell
powershell -ExecutionPolicy Bypass -File tools/dentora_voice_runtime/run-ui.ps1
```

`run-ui.ps1` temporarily generates host-local module-layer paths, starts Nuxt at `http://localhost:3000`, points it at the backend on `8100`, and restores the previous `modules.json` when it exits.

### Terminal D — microphone preflight/open UI

With terminal A runtime and terminals B/C already running:

```powershell
powershell -ExecutionPolicy Bypass -File tools/dentora_voice_runtime/microphone-e2e.ps1
```

Then log in, open Dentora Voice, click Start, allow microphone access, speak one synthetic/non-PHI command, and click Stop.

Use commands such as:

- `افتح حالة أحمد محمد`
- `اعرض آخر CBCT`
- `أظهر العصب`
- `شغل الـimplant planning`
- `Open patient Ahmed`
- `Show the nerve`
- `افتح الـCBCT بتاع Ahmed`
- `قارن الفحص الحالي بالفحص السابق`

Validate the visible state transitions and the final Dentora action. Do not record or save patient audio.

## 8. Windows network/privacy verification during STT

While the runtime is running, open another PowerShell window and run:

```powershell
powershell -ExecutionPolicy Bypass -File tools/dentora_voice_runtime/verify-network.ps1 -Seconds 30
```

During those 30 seconds, perform one microphone STT request in Dentora.

The script automatically locates the `server.py` Python process when exactly one is running and monitors its TCP connections. It fails if it observes a non-loopback remote address. It records endpoint metadata only — never audio or transcript.

If automatic PID detection is ambiguous:

```powershell
powershell -ExecutionPolicy Bypass -File tools/dentora_voice_runtime/verify-network.ps1 -RuntimePid 12345 -Seconds 30
```

Optional stronger manual verification: disconnect Wi-Fi/Ethernet temporarily and repeat an STT request. Local Voice should continue to work because the model is already on disk.

## 9. Full test gate — no skips/bypasses

Prerequisites for the repository test suite are the existing Dentora development dependencies. The validation script does not change package manifests or disable tests.

If backend dev dependencies are not already installed, use the existing project manifest:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
cd ..
```

If frontend dependencies/Chromium are not already installed:

```powershell
cd frontend
npm install
npx playwright install chromium
cd ..
```

Run the full gate from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File tools/dentora_voice_runtime/test-gate.ps1 `
  -PostgresPassword "YOUR_LOCAL_TEST_PASSWORD" `
  -BackendPython ".\backend\.venv\Scripts\python.exe"
```

The script executes, without skip or bypass:

1. Voice unit tests
2. Voice integration tests
3. Voice security/privacy tests
4. full backend pytest suite
5. Alembic round-trip tests
6. Ruff check
7. Ruff format check
8. frontend Vitest suite
9. ESLint including module layers
10. Nuxt Typecheck including host-local module layers
11. Nuxt production build
12. full Playwright E2E suite

It stops on the first failed gate and prints that gate name. Fix only the proven root cause, then rerun the same command.

## 10. What to return for final closure

After local validation, return:

- `git rev-parse HEAD`
- complete output of `verify-offline.ps1`
- `dentora-voice-benchmark.json`
- whether the real microphone chain reached the expected final state/action
- output of `verify-network.ps1`
- final `ALL LOCAL TEST GATES PASSED` result, or the first failing gate/log

Do not send real patient recordings, transcripts containing PHI, secrets, passwords, or production database data.
