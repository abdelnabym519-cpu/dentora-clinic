# Pathology Detection — module deep-dive

> Optional, removable module that adds **AI-assisted pathology
> detection on panoramic/periapical radiographs** to the patient
> clinical record. Lives as a sub-tab inside the Diagnosis mode of
> `ClinicalTab`, alongside the odontogram.

| Item | Value |
|------|-------|
| Manifest name | `pathology_detection` |
| Version | 0.1.0 |
| Category | official |
| Depends on | `patients`, `media` (read-only, no FK) |
| Installable | yes |
| Auto-installs | no — activate manually from the admin UI |
| Removable | yes (Alembic branch `pathology_detection` is isolated) |

Reference docs:

- [`docs/technical/pathology_detection/overview.md`](../technical/pathology_detection/overview.md)
- [`docs/technical/pathology_detection/permissions.md`](../technical/pathology_detection/permissions.md)
- [`docs/technical/pathology_detection/provenance.md`](../technical/pathology_detection/provenance.md)

## What it does

- Runs a DENTEX-style detector on an existing media X-ray/photo and
  stores normalized bounding boxes with confidence plus a geometric
  FDI placement (quadrant + position → FDI 11–48).
- Detects: caries, deep caries, periapical lesion, impacted tooth.
- Keeps analysis history (completed **and** failed runs) per patient.
- Advertises engine availability via `GET /capabilities` so clinics
  see exactly what to provision.

## What it does not do

- Does not ship model weights (see provenance doc — the DENTEX dataset
  is CC BY-NC-SA 4.0 and cannot ship inside this BSL product).
- Does not upload images by itself — it analyzes `media` documents.
- Does not replace a dentist's diagnosis (UI disclaimer).

## Configuration

| Setting | Default | Meaning |
|---------|---------|---------|
| `PATHOLOGY_ENGINE` | `torchvision_fasterrcnn` | engine id |
| `PATHOLOGY_MODEL_PATH` | `""` | checkpoint path (unset → 503) |
| `PATHOLOGY_DEVICE` | `cpu` | torch device |
| `PATHOLOGY_CONFIDENCE_THRESHOLD` | `0.35` | min score |
| `PATHOLOGY_NMS_IOU_THRESHOLD` | `0.5` | NMS IoU |
| `PATHOLOGY_MAX_SIDE` | `1024` | preprocessing cap |
