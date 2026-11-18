FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=5 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

# Only the OCR languages the product supports (eng+hin+pan+tel), not tesseract-ocr-all.
# Embeddings come from the Cloudflare Worker (open-source Qwen3-Embedding), so no torch/model here.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ocrmypdf tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-pan tesseract-ocr-tel \
    && rm -rf /var/lib/apt/lists/*

# Dependency layer (rebuilt only when pyproject files change).
COPY api/pyproject.toml api/pyproject.toml
COPY worker/pyproject.toml worker/pyproject.toml
RUN python - <<'EOF' > /tmp/requirements.txt
import tomllib
deps = []
for path in ("api/pyproject.toml", "worker/pyproject.toml"):
    deps += tomllib.load(open(path, "rb"))["project"]["dependencies"]
print("\n".join(sorted(set(deps))))
EOF
RUN pip install -r /tmp/requirements.txt

COPY api api
COPY worker worker
RUN pip install --no-deps ./api ./worker

RUN useradd --create-home gapfinder
USER gapfinder
CMD ["celery", "-A", "worker.app.celery_app", "worker", "--loglevel=INFO", "--concurrency=2"]
