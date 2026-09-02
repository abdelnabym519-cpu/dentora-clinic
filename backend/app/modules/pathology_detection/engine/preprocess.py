"""Radiograph preprocessing (PIL + numpy only — no OpenCV dependency).

Steps:
1. Convert to RGB (torchvision expects 3 channels).
2. Cap the long side to ``max_side``, keeping aspect ratio.
3. Export a float32 CHW tensor in [0, 1] — the torchvision
   ``fasterrcnn*`` models have no baked-in mean/std normalization, so
   no ImageNet statistics are applied (matches DENTEX-style training
   where raw grayscale RGB triples are fed directly).

The module keeps the original width/height so the service can map
normalized boxes back to the displayed image.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class PreparedImage:
    """Model-ready tensor data + original geometry."""

    array: np.ndarray  # float32, CHW, [0, 1]
    width: int  # original
    height: int  # original


def prepare(
    image: Image.Image,
    max_side: int = 1024,
) -> PreparedImage:
    """Resize (aspect preserved) and return a CHW float32 array."""
    original_w, original_h = image.size
    scale = min(1.0, max_side / max(original_w, original_h))
    if scale < 1.0:
        new_w = max(1, int(round(original_w * scale)))
        new_h = max(1, int(round(original_h * scale)))
        image = image.resize((new_w, new_h), Image.Resampling.LANCZOS)

    rgb = image.convert("RGB")
    arr = np.asarray(rgb, dtype=np.float32) / 255.0  # HWC
    arr = np.transpose(arr, (2, 0, 1))  # CHW
    return PreparedImage(
        array=np.ascontiguousarray(arr),
        width=original_w,
        height=original_h,
    )
