from pathlib import Path

from app.config import Settings


def test_defaults_are_cpu_and_production_license_gate_is_closed(monkeypatch) -> None:
    for name in (
        "ENVIRONMENT",
        "DENTORA_NERVE_MODEL_DIR",
        "DENTORA_NERVE_DEVICE",
        "DENTORA_NERVE_COMMERCIAL_USE_APPROVED",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.from_env()
    assert settings.device == "cpu"
    assert settings.model_dir == Path("/models/model")
    assert settings.commercial_use_approved is False
    assert settings.min_component_voxels == 1
