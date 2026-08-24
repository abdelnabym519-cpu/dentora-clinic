FROM python:3.10-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=1000 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    nnUNet_raw=/nnunet/raw \
    nnUNet_preprocessed=/nnunet/preprocessed \
    nnUNet_results=/nnunet/results

RUN mkdir -p /nnunet/raw /nnunet/preprocessed /nnunet/results /app

RUN python -m pip install --no-cache-dir --retries 10 --upgrade \
    pip==26.2.1 setuptools==84.0.0 wheel==0.48.0

RUN python -m pip install --no-cache-dir --retries 10 numpy==1.26.4

RUN python -m pip install --no-cache-dir --timeout 1000 --retries 10 \
    --only-binary=:all: torch==2.2.2 \
    --index-url https://download.pytorch.org/whl/cpu

RUN python -m pip install --no-cache-dir --timeout 1000 --retries 10 \
    imagecodecs==2024.6.1 \
    acvl-utils==0.2 \
    dynamic-network-architectures==0.2 \
    nnunetv2==2.2.1 \
    pydicom==3.0.2 \
    SimpleITK>=2.3,<3 \
    fastapi>=0.115,<1 \
    "uvicorn[standard]>=0.30,<1"

RUN python -m pip check && \
    python -c 'import importlib.metadata as m; import torch, numpy; print("nnunetv2:", m.version("nnunetv2")); print("torch:", torch.__version__); print("cuda_available:", torch.cuda.is_available()); print("numpy:", numpy.__version__)'

COPY app /app/app
WORKDIR /app

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
