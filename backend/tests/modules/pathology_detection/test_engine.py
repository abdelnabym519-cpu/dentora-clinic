"""torch-gated engine tests.

Skipped when the optional ``ai-pathology`` extra is not installed.
Creates a tiny random-initialized checkpoint on the fly — no training,
no bundled weights — so the real torchvision load + forward path is
exercised end to end.
"""

from __future__ import annotations

import pytest
from PIL import Image

torch = pytest.importorskip("torch")

from app.modules.pathology_detection.engine.base import EngineUnavailableError  # noqa: E402
from app.modules.pathology_detection.engine.torchvision_engine import (  # noqa: E402
    TorchvisionFasterRcnnEngine,
)


def _save_random_checkpoint(tmp_path) -> str:
    from torchvision.models.detection import fasterrcnn_mobilenet_v3_large_fpn

    model = fasterrcnn_mobilenet_v3_large_fpn(
        weights=None,
        weights_backbone=None,
        num_classes=5,
        min_size=256,
        max_size=640,
    )
    path = tmp_path / "random_smoke.pt"
    torch.save(model.state_dict(), path)
    return str(path)


def test_missing_model_path_raises_engine_unavailable() -> None:
    with pytest.raises((FileNotFoundError, EngineUnavailableError)):
        TorchvisionFasterRcnnEngine(model_path="/nonexistent/model.pt")


@pytest.fixture
async def engine(tmp_path):
    checkpoint = _save_random_checkpoint(tmp_path)
    return TorchvisionFasterRcnnEngine(
        model_path=checkpoint,
        device="cpu",
        confidence_threshold=0.0,  # keep whatever boxes the net emits
    )


@pytest.mark.asyncio
async def test_engine_loads_checkpoint_and_returns_shapes(engine) -> None:
    image = Image.new("RGB", (640, 320), (40, 40, 44))
    result = engine.analyze(image)
    assert result.engine == "torchvision_fasterrcnn"
    assert result.model_version == "random_smoke"
    assert result.inference_ms >= 0
    for finding in result.findings:
        assert finding.diagnosis in {"caries", "deep_caries", "periapical_lesion", "impacted_tooth"}
        assert 0.0 <= finding.confidence <= 1.0
        assert 0.0 <= finding.x1 <= finding.x2 <= 1.0
        assert 0.0 <= finding.y1 <= finding.y2 <= 1.0
