# Build context is expected to be the repo root (see docker-compose.yml),
# so paths below are relative to the repo root, not this file's directory.
FROM python:3.12-slim

# build-essential is included defensively: chromadb/pymupdf's dependency
# tree generally ships prebuilt manylinux wheels for this base image and
# architecture, but if any transitive dependency ever lacks one for a given
# platform, this avoids a confusing "no wheel, and no compiler" failure.
# Not verified against a real `docker build` in this environment — see
# README "Docker" section for exactly what was and wasn't checked.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first, separately from app code, so `docker build`
# can cache this layer and skip the (slow) dependency install on every
# code-only change.
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
RUN playwright install --with-deps chromium

COPY backend ./backend
COPY sample-data ./sample-data
COPY evaluation ./evaluation

ENV PYTHONPATH=/app \
    QE_COPILOT_DB_PATH=/app/data/qe_copilot.db \
    CHROMA_PERSIST_DIR=/app/data/chroma

# Persisted test-case library + vector store — mount this as a volume in
# docker-compose.yml so data survives container recreation.
RUN mkdir -p /app/data

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)" || exit 1

CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
