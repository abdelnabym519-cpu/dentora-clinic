# pathology_detection module

AI-assisted pathology detection for panoramic/periapical radiographs.
Renders inside the patient **Diagnosis** tab via the
`patient.diagnosis.subtabs` slot (order 30, after odontogram/periodontogram).

## Purpose

Detects four DENTEX-compatible abnormalities on an existing media
document (`media_kind` `xray`/`photo`):

- `caries`, `deep_caries`, `periapical_lesion`, `impacted_tooth`

Each finding stores a normalized bounding box, confidence, and a
geometric FDI place (quadrant 1–4 + position 1–8 → `tooth_number`
11–48). Analyses are immutable snapshots; a run can fail and the
failure is recorded (`status="failed"`, `error`) rather than lost.

## Public API

Mounted at `/api/v1/pathology_detection/`:

- `GET  /capabilities` — engine provisioned? model version?
- `POST /patients/{id}/analyses` — `{document_id, notes?}` → runs
  inference synchronously; 503 when the model is not provisioned,
  422 for non-analyzable documents, 404 for missing patient/document.
- `GET  /patients/{id}/analyses` — history (summaries only).
- `GET  /analyses/{id}` — detail incl. per-finding rows.
- `DELETE /analyses/{id}` — remove a run (cascade findings).

## DB schema

- `pathology_analyses` — one row per run (`clinic_id`, `patient_id`,
  `document_id` as **plain UUID, no FK to media**, `status`,
  `engine`, `model_version`, `image_width/height`, `findings_count`,
  `summary` JSONB, `error`).
- `pathology_findings` — per-detection rows (`diagnosis`,
  `confidence`, `bbox` JSONB normalized [0,1], `tooth_number`,
  `quadrant`, `position`), FK → analyses with CASCADE.

Migration branch: `pathology_0001` forking main head `0006`.

## Events

None published yet (read-only feature).

## Permissions

`pathology_detection.read` / `pathology_detection.write` declared via
`get_permissions()`; manifest grants: admin `*`, dentist both,
hygienist/assistant read, receptionist none.

## Engine layer (framework-decoupled)

`engine/base.py` — Protocol + factory (`get_engine`); raises
`EngineUnavailableError` when `PATHOLOGY_MODEL_PATH` is empty.
`engine/torchvision_engine.py` — lazy torch import, Faster R-CNN
(MobileNetV3/FPN, 5 classes). `engine/preprocess.py` — PIL/numpy only.
`engine/postprocess.py` — confidence filter, geometric FDI
enumeration (pure functions, unit-tested).

## Licensing / provenance — READ BEFORE TOUCHING

Dentora ships **no weights**. The public DENTEX dataset is
CC BY-NC-SA 4.0 (non-commercial) and cannot be shipped inside this
BSL 1.1 product. Checkpoints come from operator-licensed data via
`training/train_smoke.py` (synthetic smoke) or a production pipeline
(documented in `docs/technical/pathology_detection/provenance.md`).

## Gotchas

- Never `import torch` at module import time — the optional
  `ai-pathology` extra is not installed in the core image.
- Inference runs in `asyncio.to_thread`; keep it that way.
- `document_id` is deliberately NOT a FK (clean uninstall).
