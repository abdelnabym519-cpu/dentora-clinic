# Dentora Voice local runtime

This process is deliberately separate from the Dentora backend. It performs speech-to-text locally with `faster-whisper` and binds only to `127.0.0.1`.

## Privacy properties

- No cloud speech API is used.
- The runtime does not download models automatically (`local_files_only=True`).
- Audio is accepted from the local browser, written only to a temporary decoder file, and deleted before the response completes.
- Uvicorn access logging is disabled by the provided launcher.
- Transcript text is returned to the local Dentora page and is not persisted by the runtime.

## Install

Create a dedicated Python environment for this runtime; do not add these ML packages to the Dentora backend environment.

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r tools/dentora_voice_runtime/requirements.txt
```

Provide a locally prepared CTranslate2 faster-whisper model directory. The default is:

`models/faster-whisper-small`

Override it with `DENTORA_VOICE_MODEL_PATH`. CPU INT8 is the default. Optional GPU experiments can set `DENTORA_VOICE_DEVICE=cuda` and a supported compute type; GPU is not required by Dentora Voice.

## Run

```bash
python tools/dentora_voice_runtime/server.py
```

Health endpoint: `http://127.0.0.1:8765/health`.

## Base vs small benchmark

Use local `base` and `small` multilingual CTranslate2 model directories and local audio samples. Do not commit patient recordings or benchmark audio containing PHI.

```bash
python tools/dentora_voice_runtime/benchmark.py \
  --base-model models/faster-whisper-base \
  --small-model models/faster-whisper-small \
  --sample path/to/arabic-command.wav \
  --sample path/to/english-command.wav \
  --sample path/to/mixed-command.wav
```

The report contains model load time, process RSS, transcription latency, audio duration and real-time factor. It deliberately does not write recognized text into the report.

## Required validation commands

Use synthetic/non-PHI recordings for phrases such as:

- افتح حالة أحمد محمد
- اعرض آخر CBCT
- أظهر العصب
- شغل الـimplant planning
- Open patient Ahmed
- Show the nerve
- افتح الـCBCT بتاع Ahmed

Hardware benchmark results are workstation-specific and must not be inferred from CI or another machine.
