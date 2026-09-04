# Changelog

## [0.1.0] - 2026-09-02

### Added

- Pathology detection module (backend): models, schemas, service,
  router, isolated Alembic branch `pathology_0001`.
- DENTEX-compatible label space: caries, deep caries, periapical
  lesion, impacted tooth (`constants.py`).
- Framework-decoupled inference engine: `PathologyEngine` protocol,
  torchvision Faster R-CNN (MobileNetV3/FPN) implementation,
  PIL/numpy preprocessing, geometric FDI enumeration.
- API: capabilities, run/list/get/delete analysis endpoints with
  `pathology_detection.read/write` permissions.
- Optional `ai-pathology` extra in `pyproject.toml` (torch +
  torchvision). No weights bundled; `PATHOLOGY_MODEL_PATH` configurable.
- Synthetic smoke trainer (`training/train_smoke.py`) for checkpoint
  provisioning and CI validation.
- Frontend layer: pathology subtab in the Diagnosis tab
  (`patient.diagnosis.subtabs`, order 30), image picker, findings
  overlay, history list, i18n (en/es/fr/pt).
- Unit + API tests under `tests/modules/pathology_detection/`.

### Security / licensing

- Zero pretrained weight shipping; DENTEX-derived weights are
  non-commercial (CC BY-NC-SA 4.0) and intentionally excluded.
