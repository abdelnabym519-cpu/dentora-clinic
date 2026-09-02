# Pathology Detection — overview

> Optional, removable module that adds **AI-assisted pathology
> detection on panoramic/periapical radiographs** to the patient
> clinical record. Renders as a sub-tab inside the Diagnosis mode of
> `ClinicalTab`, alongside the odontogram and periodontogram.

| Item | Value |
|------|-------|
| Manifest name | `pathology_detection` |
| Version | 0.1.0 |
| Category | official |
| Depends on | `patients`, `media` (both read-only — no FK) |
| Installable | yes |
| Auto-installs | no — activate manually from the admin UI |
| Removable | yes (Alembic branch `pathology_detection` is isolated) |
| Optional runtime extra | `ai-pathology` (torch + torchvision) |

## What it does

- Runs a DENTEX-style detector on an existing media document
  (`media_kind` `xray`/`photo`) and stores the result as an immutable
  analysis snapshot.
- Detects four diagnoses: **caries**, **deep caries**,
  **periapical lesion**, **impacted tooth**.
- Stores per-finding normalized bounding boxes, confidence, and a
  geometric FDI placement (quadrant + position → `tooth_number`
  11–48) so findings line up with the odontogram's FDI numbering.
- Exposes capabilities advertising so the UI can explain a
  *not-yet-provisioned* engine instead of failing opaque.
- Persists failed runs (`status="failed"`, `error`) for auditability.

## What it does not do

- It does **not ship weights**. The engine loads a checkpoint from
  `PATHOLOGY_MODEL_PATH`; provisioning is operator responsibility
  (see [provenance.md](./provenance.md) for the licensing analysis).
- It does not auto-upload images — it analyzes media documents already
  in the patient record.
- It is a screening aid; the UI always carries a non-diagnosis
  disclaimer.

## Endpoints

| Method | Path | Permission |
|--------|------|------------|
| GET | `/api/v1/pathology_detection/capabilities` | `pathology_detection.read` |
| POST | `/api/v1/pathology_detection/patients/{id}/analyses` | `pathology_detection.write` |
| GET | `/api/v1/pathology_detection/patients/{id}/analyses` | `pathology_detection.read` |
| GET | `/api/v1/pathology_detection/analyses/{id}` | `pathology_detection.read` |
| DELETE | `/api/v1/pathology_detection/analyses/{id}` | `pathology_detection.write` |

Error mapping: 404 patient/document/analysis, 422 non-analyzable
media kind, 503 engine not provisioned.

## Data model

- `pathology_analyses` — one row per run (`document_id` is a plain
  UUID, deliberately no FK to `documents` for clean uninstall),
  frozen `summary` JSONB counts, `model_version`, `inference_ms`.
- `pathology_findings` — per-detection rows (diagnosis, confidence,
  `bbox` JSONB normalized [0,1], tooth FDI fields), CASCADE on delete.

## Engine layer

`engine/base.py` (Protocol + factory, `EngineUnavailableError`),
`engine/torchvision_engine.py` (lazy torch import, Faster R-CNN
MobileNetV3/FPN 5-class head), `engine/preprocess.py` (PIL/numpy — no
OpenCV), `engine/postprocess.py` (confidence filtering + geometric FDI
enumeration). See [provenance.md](./provenance.md) and the module
`CLAUDE.md` for gotchas (never import torch at module import time).
