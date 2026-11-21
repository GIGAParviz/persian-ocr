FROM python:3.12-slim-trixie

LABEL org.opencontainers.image.source="https://github.com/GIGAParviz/persian-ocr" \
      org.opencontainers.image.title="persian-ocr" \
      org.opencontainers.image.version="0.2.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    PERSIAN_OCR_HOST=0.0.0.0 \
    PERSIAN_OCR_PORT=8000 \
    HOME=/tmp

WORKDIR /app

COPY requirements.txt requirements.lock ./
RUN pip install --no-deps -r requirements.lock

ARG INDRA_REVISION=bd02167fdf2005a19962cc15188f8496a2c87d3b
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('datalab-to/indra-ocr', revision='${INDRA_REVISION}', local_dir='indra-ocr', allow_patterns=['det.onnx', 'rec.onnx', 'rec_rtl.onnx', 'rec_cjk.onnx', 'rec_world.onnx', 'order.onnx', 'orient.onnx', 'script.onnx', 'mathcls.onnx', 'meta.json', 'config.json', 'lm.npz', 'lm_cjk.npz', 'lm_world.npz', 'LICENSE'])" \
    && rm -rf indra-ocr/.cache /tmp/.cache

COPY persian_ocr/ persian_ocr/
COPY evaluation/ evaluation/

RUN mkdir -p .cache output && chown -R 1000:1000 .cache output

USER 1000:1000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

CMD ["python", "-m", "persian_ocr", "serve"]
