# Pathology Detection — research, licenses, model provenance

This document records the open-source research performed for the
feature, the project selected as the foundation, the license analysis,
and the weight-provisioning policy. It is the reference for any future
model swap.

## 1. Candidates evaluated

| Project | License (repo) | Data license | Weights in repo? | Verdict |
|---------|----------------|--------------|------------------|---------|
| [DENTEX 2023](https://github.com/ibrahimethemhamamci/DENTEX) (MICCAI challenge, official) | **MIT** (repo code) | **CC BY-NC-SA 4.0** (dataset) | no | ✅ methodology + label space; ❌ data/weights cannot ship commercially |
| [awerdich/dentexmodel](https://github.com/awerdich/dentexmodel) (CCB HMS code template + DENTEX notebooks) | **CC-BY-4.0** | CC BY-NC-SA 4.0 | no (repo is 27 MB of docs/images; `src/` is 80 KB) | ⚠️ permissive code, but no weights and heavy TF/Torch template |
| [liangyuandg/DLCariesScreen](https://github.com/liangyuandg/DLCariesScreen) | research repo | oral photos | external download | ❌ not panoramic, no license file, unclear provenance |
| [Loki-Silvres/Dental-Disease-Detection](https://github.com/Loki-Silvres/Dental-Disease-Detection) | research repo (Flask + Kaggle weights) | Kaggle | no | ❌ 31-class segmentation, no license file, Kaggle weights behind sign-in |
| [AndreyGermanov/yolov8_caries_detector](https://github.com/AndreyGermanov/yolov8_caries_detector) | **GPL-3.0** | DentalAI (Supervisely) | yes (best.pt) | ❌ **GPL copyleft is incompatible with Dentora's BSL 1.1** |
| [MIC-DKFZ/ToothSeg](https://github.com/MIC-DKFZ/ToothSeg) | (nnU-Net research) | ToothFairy2 / Zenodo | external (Zenodo) | ❌ CBCT segmentation (not panoramic pathology), Zenodo blocked, classifier focus mismatch |
| Kartik-Hiremath/dental-radiography-analysis | research notebooks | external dataset | no | ❌ no license, no weights |

## 2. Selection decision

**Foundation: the DENTEX 2023 task definition + label space** —
quadrant/enumeration/diagnosis on panoramic X-rays with FDI numbering
and the four diagnoses `caries`, `deep_caries`,
`periapical_lesion`, `impacted_tooth` (paper: *DENTEX: Dental
Enumeration and Tooth Pathosis Detection on Panoramic X-rays*,
MICCAI 2023, CC BY 4.0 paper; evaluation code MIT).

Reasons:

1. **Only clinically coherent label space for a dental EHR**: it
   provides FDI tooth enumeration (11–48), which is exactly what
   Dentora's odontogram already uses — findings can be attached to the
   same tooth numbering without a mapping layer.
2. **License-clean code path**: the official repo's code is MIT; the
   awerdich repo (the reference implementation used by a DENTEX final
   team) is CC-BY-4.0. Both permit reimplementation.
3. **No weight licensing trap**: since the DENTEX *dataset* is
   CC BY-NC-SA 4.0 (non-commercial), shipping a model trained on it
   inside a BSL 1.1 product would violate the dataset license. The
   feature therefore reimplements the architecture in-house
   (torchvision Faster R-CNN — BSD-3-Clause/PyTorch license, no
   copyleft) and requires operator-provisioned weights.

## 3. What ships in this repository

- **Code only.** DENTEX-inspired detection architecture
  (`fasterrcnn_mobilenet_v3_large_fpn`, 5-class head), preprocessing,
  geometric FDI enumeration, module/API/UI integration — all original
  implementation.
- **No weights, no dataset images, no DENTEX-derived artifacts.**
  The UI/API degrade gracefully (`GET /capabilities` → `available:
  false`, analyze → 503) until a checkpoint is provisioned.
- Optional extra `ai-pathology` (torch + torchvision) keeps the core
  install lean; both are permissively licensed.

## 4. Weight provisioning policy

```bash
# 1) Smoke checkpoint for demos/CI (synthetic, NOT clinically valid)
pip install -e backend[ai-pathology]
python -m app.modules.pathology_detection.training.train_smoke \
  --epochs 5 --images 80 --out /tmp/pathology-weights

# 2) Production: train the same head on licensed clinical data
# (own annotations, or DENTEX data under a separate non-commercial
# license/agreement — never bundled with this product).
export PATHOLOGY_MODEL_PATH=/tmp/pathology-weights/pathology_smoke.pt
export PATHOLOGY_CONFIDENCE_THRESHOLD=0.35
export PATHOLOGY_NMS_IOU_THRESHOLD=0.5
```

Checkpoint format: plain `state_dict` of
`torchvision.models.detection.fasterrcnn_mobilenet_v3_large_fpn(num_classes=5)`
(not exported here). `metadata.json` alongside the checkpoint records
engine, dataset, and validation stats; the backend persists
`model_version` (checkpoint stem) per analysis for auditability.

## 5. Known limitations

- **Smoke model is a synthetic-data pipeline test**, not a clinical
  model; no diagnostic claim is made until a checkpoint trained on
  appropriate clinical data with adequate validation is provisioned.
- FDI enumeration is **geometric** (quadrant from box center,
  position by x-order) — the documented DENTEX-style heuristic. It is
  deterministic and unit-tested, but models that predict enumeration
  directly would replace `engine/postprocess.py` without an API change.
- Synchronous analysis: a single CPU inference on a 1024px image is
  ~1s; clinics needing bulk runs would add a queue (out of scope).
- No segmentation masks — detector boxes only (matches DENTEX task 3).
