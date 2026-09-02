"""Unit tests for the radiograph preprocessing helpers."""

from __future__ import annotations

from PIL import Image

from app.modules.pathology_detection.engine.preprocess import prepare


def test_prepare_returns_chw_float_01() -> None:
    image = Image.new("RGB", (64, 48), (128, 128, 128))
    prepared = prepare(image, max_side=1024)

    assert prepared.array.shape == (3, 48, 64)
    assert prepared.array.dtype.name == "float32"
    assert prepared.array.min() >= 0.0
    assert prepared.array.max() <= 1.0
    assert (prepared.width, prepared.height) == (64, 48)


def test_prepare_caps_long_side_and_keeps_aspect() -> None:
    image = Image.new("RGB", (2000, 1000), (64, 64, 64))
    prepared = prepare(image, max_side=512)

    h, w = prepared.array.shape[1], prepared.array.shape[2]
    assert max(h, w) == 512
    assert abs(w / h - 2.0) < 0.05  # aspect ratio preserved
    assert (prepared.width, prepared.height) == (2000, 1000)
