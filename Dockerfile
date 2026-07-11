FROM node:22-alpine AS web-build

WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=5 \
    VOC_DB_PATH=/app/data/guardian_voc.duckdb \
    VOC_DATA_DIR=/app/data \
    VOC_INBOX_DIR=/app/data/inbox

WORKDIR /app

RUN adduser --disabled-password --gecos "" --home /home/guardian guardian

COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir --require-hashes --requirement requirements.lock

COPY README.md ./
COPY guardian_voc ./guardian_voc
COPY social_crawler ./social_crawler
RUN pip install --no-cache-dir --no-deps --no-build-isolation .

COPY fixtures ./fixtures
COPY scripts ./scripts
COPY --from=web-build /build/web/dist ./web/dist

RUN mkdir -p /app/data/inbox /app/data/quarantine \
    && chown -R guardian:guardian /app/data /home/guardian \
    && chmod 0755 /app

USER guardian
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=4 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready', timeout=2)" || exit 1

CMD ["python", "-m", "guardian_voc", "serve", "--host", "0.0.0.0", "--port", "8000"]
