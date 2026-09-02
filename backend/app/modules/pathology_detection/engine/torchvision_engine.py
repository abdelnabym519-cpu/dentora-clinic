"""torchvision Faster R-CNN engine (optional ``ai-pathology`` extra).

Architecture: ``fasterrcnn_mobilenet_v3_large_fpn`` with 5 output
classes (background + the four DENTEX diagnoses). This is a light
CPU-friendly detector: on a 2-core sandbox a 1024px panoramic image
resolves in roughly a second per image, which keeps the first
integration (synchronous POST) usable at clinic scale.

Downloading/weight provenance: the engine **only loads** the checkpoint
path supplied by ``PATHOLOGY_MODEL_PATH``. It never downloads weights.
Dentora's repository does not contain DENTEX-derived weights because
the DENTEX dataset is CC BY-NC-SA 4.0 (non-commercial) while Dentora
is Business Source 1.1; operators train or license their own data and
provision a checkpoint.

The checkpoint is a plain ``state_dict`` for the default
``fasterrcnn_mobilenet_v3_large_fpn`` construction with
``num_classes=5`` (e.g. produced by ``training/train_smoke.py`` or a
production training run).
"""

from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from .base import DetectedFinding, InferenceResult
from .preprocess import prepare

BACKBONE = "fasterrcnn_mobilenet_v3_large_fpn"


class TorchvisionFasterRcnnEngine:
    """Faster R-CNN (MobileNetV3/FPN) detector backed by torchvision."""

    name = "torchvision_fasterrcnn"

    def __init__(
        self,
        model_path: str,
        device: str = "cpu",
        confidence_threshold: float = 0.35,
        nms_iou_threshold: float = 0.5,
        max_side: int = 1024,
    ) -> None:
        import torch
        from torchvision.models.detection import fasterrcnn_mobilenet_v3_large_fpn

        checkpoint = Path(model_path)
        if not checkpoint.is_file():
            raise FileNotFoundError(f"Pathology model checkpoint not found: {checkpoint}")

        model = fasterrcnn_mobilenet_v3_large_fpn(
            weights=None,
            weights_backbone=None,
            num_classes=5,
        )
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        if isinstance(state, dict) and "model" in state and "state_dict" not in state:
            # Training scripts may save {"model": state_dict, ...}.
            state = state["model"]
        model.load_state_dict(state)
        model.eval()

        self._model = model
        self._device = device
        self._confidence_threshold = float(confidence_threshold)
        self._nms_iou_threshold = float(nms_iou_threshold)
        self._max_side = int(max_side)
        self.model_version = checkpoint.stem

    def analyze(self, image: Image.Image) -> InferenceResult:
        """Run one image through the detector.

        Returns normalized boxes (original image coordinates → [0,1]),
        diagnose labels and confidences. NMS is applied by
        ``GeneralizedRCNN`` already; the legacy per-class
        ``self._nms_iou_threshold`` is kept for API symmetry and used
        for an extra deterministic cleanup pass.
        """
        import torch
        from torchvision.ops import nms

        prepared = prepare(image, max_side=self._max_side)
        array = prepared.array
        tensor = torch.from_numpy(array).unsqueeze(0)  # [1, 3, H, W]

        started = time.perf_counter()
        with torch.no_grad():
            prediction = self._model(tensor)[0]
        inference_ms = int((time.perf_counter() - started) * 1000)

        boxes = prediction["boxes"].cpu()
        scores = prediction["scores"].cpu()
        labels = prediction["labels"].cpu()

        keep = nms(boxes, scores, self._nms_iou_threshold)
        boxes, scores, labels = boxes[keep], scores[keep], labels[keep]

        findings: list[DetectedFinding] = []
        for box, score, label in zip(boxes, scores, labels, strict=False):
            conf = float(score)
            if conf < self._confidence_threshold:
                continue
            class_index = int(label)
            diagnosis = _diagnosis_for_index(class_index)
            if diagnosis is None:
                continue

            x1, y1, x2, y2 = (float(v) for v in box.tolist())
            # Normalize against the tensor's actual size, then clamp.
            h = float(prepared.array.shape[1])
            w = float(prepared.array.shape[2])
            findings.append(
                DetectedFinding(
                    diagnosis=diagnosis,
                    confidence=conf,
                    x1=min(1.0, max(0.0, x1 / w)),
                    y1=min(1.0, max(0.0, y1 / h)),
                    x2=min(1.0, max(0.0, x2 / w)),
                    y2=min(1.0, max(0.0, y2 / h)),
                )
            )

        return InferenceResult(
            findings=findings,
            engine=self.name,
            model_version=self.model_version,
            inference_ms=inference_ms,
        )


def _diagnosis_for_index(class_index: int) -> str | None:
    from app.modules.pathology_detection.constants import CLASS_INDEX_TO_DIAGNOSIS

    return CLASS_INDEX_TO_DIAGNOSIS.get(class_index)
