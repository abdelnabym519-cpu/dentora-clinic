"""Checkpoint provisioning toolkit for the pathology detection module.

* ``train_smoke.py`` — synthetic-data smoke trainer. Produces a
  checkpoint that exercises the whole pipeline (preprocess → detector
  → postprocess → FDI) in CI/demo environments. **Never clinically
  validated**; only for integration validation.
* Production training uses the same model head on licensed clinical
  data — see ``docs/technical/pathology_detection/provenance.md``.
"""
