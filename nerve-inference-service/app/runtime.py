from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import Settings
from .postprocess import ImageGeometry


class ModelRuntimeError(RuntimeError):
    def __init__(self, message: str, *, initialization: bool = False) -> None:
        self.initialization = initialization
        super().__init__(message)


@dataclass(frozen=True)
class RuntimeOutput:
    segmentation_zyx: np.ndarray
    geometry: ImageGeometry
    confidence: float
    model_id: str
    model_version: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class DentalSegmentatorRuntime:
    """Lazy, single-process nnU-Net runtime kept outside Dentora's backend."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._predictor = None
        self._torch = None
        self._model_version = "uninitialized"

    @property
    def configured(self) -> bool:
        return self._settings.model_dir.exists()

    def _load(self) -> None:
        if self._predictor is not None:
            return
        model_dir = self._settings.model_dir
        dataset_path = model_dir / "dataset.json"
        plans_path = model_dir / "plans.json"
        checkpoint = model_dir / "fold_0" / "checkpoint_final.pth"
        if not dataset_path.is_file() or not plans_path.is_file() or not checkpoint.is_file():
            raise ModelRuntimeError("configured DentalSegmentator model files are incomplete", initialization=True)
        try:
            dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelRuntimeError("DentalSegmentator dataset metadata is invalid", initialization=True) from exc
        labels = dataset.get("labels", {})
        if labels.get("Mandibular canal") != 5 or dataset.get("file_ending") != ".nii.gz":
            raise ModelRuntimeError("configured model does not match the expected DentalSegmentator contract", initialization=True)

        try:
            import torch
            from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor
        except ImportError as exc:
            raise ModelRuntimeError("nnU-Net runtime dependencies are unavailable", initialization=True) from exc

        if self._settings.device == "cuda" and not torch.cuda.is_available():
            raise ModelRuntimeError("CUDA was requested but is not available", initialization=True)
        device = torch.device(self._settings.device)
        if self._settings.device == "cpu":
            torch.set_num_threads(self._settings.cpu_threads)
            torch.set_num_interop_threads(1)
        predictor = nnUNetPredictor(
            tile_step_size=0.5,
            use_gaussian=True,
            use_mirroring=False,
            perform_everything_on_gpu=self._settings.device == "cuda",
            device=device,
            verbose=False,
            verbose_preprocessing=False,
            allow_tqdm=False,
        )
        try:
            predictor.initialize_from_trained_model_folder(
                model_training_output_dir=str(model_dir),
                use_folds=(0,),
                checkpoint_name="checkpoint_final.pth",
            )
        except Exception as exc:
            raise ModelRuntimeError("DentalSegmentator checkpoint initialization failed", initialization=True) from exc
        self._predictor = predictor
        self._torch = torch
        self._model_version = f"v100-checkpoint-{_sha256_file(checkpoint)[:12]}"

    def _mean_canal_probability(self, logits) -> float:
        torch = self._torch
        if torch is None:
            raise ModelRuntimeError("model runtime is not initialized")
        total = 0.0
        count = 0
        # Chunk along the first spatial axis to keep temporary float32 softmax memory bounded.
        for start in range(0, int(logits.shape[1]), 16):
            chunk = logits[:, start : start + 16].float()
            predicted = chunk.argmax(dim=0)
            mask = predicted == 5
            n = int(mask.sum().item())
            if n:
                probability = torch.softmax(chunk, dim=0)[5]
                total += float(probability[mask].sum().item())
                count += n
            del chunk, predicted, mask
        return 0.0 if count == 0 else max(0.0, min(1.0, total / count))

    def infer(self, dicom_files: tuple[Path, ...], work_dir: Path) -> RuntimeOutput:
        self._load()
        predictor = self._predictor
        torch = self._torch
        if predictor is None or torch is None:
            raise ModelRuntimeError("model runtime is not initialized")
        try:
            import SimpleITK as sitk
            from nnunetv2.inference.export_prediction import export_prediction_from_logits
        except ImportError as exc:
            raise ModelRuntimeError("medical image runtime dependencies are unavailable", initialization=True) from exc

        try:
            reader = sitk.ImageSeriesReader()
            reader.SetFileNames([str(path) for path in dicom_files])
            source = reader.Execute()
            if source.GetDimension() != 3 or any(value <= 0 for value in source.GetSpacing()):
                raise ModelRuntimeError("DICOM series geometry is invalid")
            input_path = work_dir / "case_0000.nii.gz"
            sitk.WriteImage(source, str(input_path), True)

            preprocessor = predictor.configuration_manager.preprocessor_class(verbose=False)
            data, seg, properties = preprocessor.run_case(
                [str(input_path)],
                None,
                predictor.plans_manager,
                predictor.configuration_manager,
                predictor.dataset_json,
            )
            tensor = torch.from_numpy(data).contiguous().float()
            del data, seg
            logits = predictor.predict_logits_from_preprocessed_data(tensor)
            del tensor
            confidence = self._mean_canal_probability(logits)

            output_base = work_dir / "prediction"
            export_prediction_from_logits(
                logits,
                properties,
                predictor.configuration_manager,
                predictor.plans_manager,
                predictor.dataset_json,
                str(output_base),
                save_probabilities=False,
            )
            del logits
            output = sitk.ReadImage(str(output_base) + ".nii.gz")
            geometry_equal = (
                source.GetSize() == output.GetSize()
                and np.allclose(source.GetSpacing(), output.GetSpacing(), atol=1e-6)
                and np.allclose(source.GetOrigin(), output.GetOrigin(), atol=1e-6)
                and np.allclose(source.GetDirection(), output.GetDirection(), atol=1e-6)
            )
            if not geometry_equal:
                raise ModelRuntimeError("model output did not preserve native DICOM geometry")
            segmentation = sitk.GetArrayFromImage(output)
            geometry = ImageGeometry(
                size_xyz=tuple(int(value) for value in output.GetSize()),
                spacing_xyz=tuple(float(value) for value in output.GetSpacing()),
                origin_lps=tuple(float(value) for value in output.GetOrigin()),
                direction=tuple(float(value) for value in output.GetDirection()),
            )
            return RuntimeOutput(
                segmentation_zyx=segmentation,
                geometry=geometry,
                confidence=confidence,
                model_id="DentalSegmentator/Dataset112",
                model_version=self._model_version,
            )
        except ModelRuntimeError:
            raise
        except Exception as exc:
            raise ModelRuntimeError("DentalSegmentator inference failed") from exc
