# Render free web service: API + inline job runner in ONE process (TASK_RUNNER=inline). Embeddings come
# from the Cloudflare Worker (open-source Qwen3-Embedding-0.6B), the same as locally. No torch, no
# worker, no local Redis. Build context = repository root.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DEFAULT_TIMEOUT=120 \
    ENVIRONMENT=production TASK_RUNNER=inline \
    PYTHONPATH=/app/api:/app:/app/worker MALLOC_ARENA_MAX=2

# OCR for scanned PDFs only (eng+hin+pan+tel). Heavy: large scanned PDFs can hit the 512 MB free-tier RAM limit.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ocrmypdf tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-pan tesseract-ocr-tel \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY api/pyproject.toml api/pyproject.toml
COPY worker/pyproject.toml worker/pyproject.toml
RUN python - <<'PY' > /tmp/requirements.txt
import tomllib
deps = []
for path in ("api/pyproject.toml", "worker/pyproject.toml"):
    deps += tomllib.load(open(path, "rb"))["project"]["dependencies"]
print("\n".join(sorted(set(deps))))
PY
RUN pip install -r /tmp/requirements.txt

COPY api api
COPY worker worker
RUN useradd --create-home gapfinder && chown -R gapfinder /app
USER gapfinder
WORKDIR /app/api
# Render injects PORT (default 10000).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips='*'"]
