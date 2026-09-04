"""Synthetic smoke trainer for the pathology detection engine.

Purpose: produce a checkpoint that makes the **complete** integration
path runnable (load checkpoint → preprocess → Faster R-CNN forward →
NMS → confidence filter → FDI enumeration → API/UI), and to serve as
the canonical training-loop example for production runs on licensed
clinical data.

The image synthesizer draws a radiograph-like panoramic X-ray (dark
background, bright tooth ellipses along two jaw arcs, darker lesion
patches) with ground-truth boxes per diagnosis. The resulting model is
**not clinically valid** — use it only for demos, pipeline tests and CI.

Usage (requires the ``ai-pathology`` extra)::

    python -m app.modules.pathology_detection.training.train_smoke \\
        --epochs 5 --images 80 --out /tmp/pathology-weights \\
        --max-side 640

Then point the backend at the checkpoint::

    PATHOLOGY_MODEL_PATH=/tmp/pathology-weights/pathology_smoke.pt
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

SEED = 20260902

# Class layout mirrors constants.py: index 0 = background.
DIAGNOSES = ("caries", "deep_caries", "periapical_lesion", "impacted_tooth")
NUM_CLASSES = len(DIAGNOSES) + 1
IMG_W, IMG_H = 640, 320


@dataclass
class Sample:
    image: Image.Image
    boxes: list[list[float]] = field(default_factory=list)
    labels: list[int] = field(default_factory=list)
    diagnoses: list[str] = field(default_factory=list)


def _lesion_patch(
    draw: ImageDraw.ImageDraw, cx: float, cy: float, radius: float, shade: int
) -> None:
    """Dark irregular radiolucent patch (caries / lesion look)."""
    points = []
    for step in range(8):
        angle = step * math.tau / 8
        wobble = radius * (0.7 + random.random() * 0.5)
        points.append((cx + math.cos(angle) * wobble, cy + math.sin(angle) * wobble))
    draw.polygon(points, fill=(shade, shade, shade))


def synthesize_sample(rng: random.Random, index: int = 0) -> Sample:
    """Draw one fake panoramic radiograph with annotated lesions."""
    img = Image.new("RGB", (IMG_W, IMG_H), (24, 24, 26))
    draw = ImageDraw.Draw(img)

    # Soft jaw gradient.
    for y in range(IMG_H):
        shade = 26 + int(8 * math.sin(y / IMG_H * math.pi))
        draw.line([(0, y), (IMG_W, y)], fill=(shade, shade, shade + 2))

    tooth_slots: list[tuple[float, float]] = []
    for quadrant_x in (0, 1):
        for tooth in range(8):
            # two arches: upper (y≈90), lower (y≈230)
            for arch_y in (90, 230):
                base_x = 55 + quadrant_x * 265 + tooth * 22
                x = base_x + rng.uniform(-3, 3)
                y = arch_y + (8 if tooth in (0, 7) else 0) + rng.uniform(-3, 3)
                tooth_slots.append((x, y))

    for x, y in tooth_slots:
        w = rng.uniform(12, 15)
        h = rng.uniform(26, 32)
        draw.ellipse([x - w / 2, y - h / 2, x + w / 2, y + h / 2], fill=(168, 168, 172))

    sample = Sample(image=img)
    lesion_count = rng.randint(0, 4)
    for _ in range(lesion_count):
        x, y = rng.choice(tooth_slots)
        diagnosis = rng.choice(DIAGNOSES)
        radius = rng.uniform(4, 7)
        _lesion_patch(draw, x, y, radius, shade=rng.randint(72, 108))
        sample.boxes.append([x - radius, y - radius, x + radius, y + radius])
        sample.labels.append(DIAGNOSES.index(diagnosis) + 1)
        sample.diagnoses.append(diagnosis)
    return sample


def make_dataset(count: int) -> list[Sample]:
    rng = random.Random(SEED + count)
    return [synthesize_sample(rng, i) for i in range(count)]


def train(epochs: int, images: int, out_dir: Path, max_side: int) -> Path:
    """Run the smoke training loop; returns the checkpoint path."""
    import torch
    from torchvision.models.detection import fasterrcnn_mobilenet_v3_large_fpn

    train_count = max(16, images - 16)
    samples = make_dataset(images)
    val = samples[train_count:]
    train = samples[:train_count]

    def to_targets(sample: Sample):
        boxes = (
            torch.tensor(sample.boxes, dtype=torch.float32) if sample.boxes else torch.zeros((0, 4))
        )
        labels = (
            torch.tensor(sample.labels, dtype=torch.int64)
            if sample.labels
            else torch.zeros((0,), dtype=torch.int64)
        )
        return {"boxes": boxes, "labels": labels}

    def tensors(sample: Sample):
        arr = np.asarray(sample.image.convert("RGB"), dtype=np.float32) / 255.0
        arr = np.transpose(arr, (2, 0, 1))
        return torch.from_numpy(arr.copy())

    model = fasterrcnn_mobilenet_v3_large_fpn(
        weights=None,
        weights_backbone=None,
        num_classes=NUM_CLASSES,
        # Keep the CPU smoke run fast and deterministic.
        min_size=256,
        max_size=max_side,
    )
    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.Adam(params, lr=1e-4)
    model.train()

    for epoch in range(epochs):
        epoch_loss = 0.0
        for sample in train:
            images = [tensors(sample)]
            targets = [to_targets(sample)]
            loss_dict = model(images, targets)
            losses = sum(loss for loss in loss_dict.values())
            optimizer.zero_grad()
            losses.backward()
            optimizer.step()
            epoch_loss += float(losses)
        print(f"epoch {epoch + 1}/{epochs}: loss={epoch_loss / len(train):.4f}")

    # Evaluate: simple hit-rate = boxes whose center lands in a GT box.
    model.eval()
    hits = total = 0
    with torch.no_grad():
        for sample in val:
            pred = model([tensors(sample)])[0]
            for box in pred["boxes"].tolist():
                cx = (box[0] + box[2]) / 2
                cy = (box[1] + box[3]) / 2
                total += 1
                if any(
                    gx1 <= cx <= gx2 and gy1 <= cy <= gy2 for gx1, gy1, gx2, gy2 in sample.boxes
                ):
                    hits += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = out_dir / "pathology_smoke.pt"
    torch.save(model.state_dict(), checkpoint)
    meta = {
        "engine": "torchvision_fasterrcnn",
        "architecture": "fasterrcnn_mobilenet_v3_large_fpn",
        "num_classes": NUM_CLASSES,
        "diagnoses": list(DIAGNOSES),
        "model_version": checkpoint.stem,
        "trained_at": datetime.now(UTC).isoformat(),
        "dataset": "synthetic smoke (no clinical data, NOT clinically validated)",
        "validation": {"detections": total, "center_hits": hits},
        "notes": "Integration/CI only. Production requires licensed clinical data.",
    }
    (out_dir / "metadata.json").write_text(json.dumps(meta, indent=2))
    print(f"center-hit rate: {hits}/{total}")
    print(f"saved: {checkpoint}")
    return checkpoint


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--images", type=int, default=80)
    parser.add_argument("--out", type=Path, default=Path("/tmp/pathology-weights"))
    parser.add_argument("--max-side", type=int, default=640)
    args = parser.parse_args(argv)
    try:
        train(args.epochs, args.images, args.out, args.max_side)
    except ModuleNotFoundError as exc:
        print(
            f"ERROR: {exc} — install the ai-pathology extra first (pip install .[ai-pathology])",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
