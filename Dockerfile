# Shared image for api / crawler / scheduler / dashboard — compose picks command per service.
# Build targets: test (lint+pytest) → prod (= base, non-root, no dev deps). Default = base.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY config/ ./config/
COPY app/ ./app/
COPY dashboard/ ./dashboard/
COPY scripts/ ./scripts/
COPY scrapers/ ./scrapers/

# non-root runtime (uid/gid auto = 1000 in clean image = host user → bind mounts writable);
# data/ logs/ are volume mount points, chowned so freshly created named volumes are writable
RUN useradd --create-home appuser \
    && mkdir -p /app/data /app/logs \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000 8501

# default = FastAPI backend; other services override command + healthcheck in compose
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]
