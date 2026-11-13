# syntax=docker/dockerfile:1

# --- build the web app -------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# vite writes to ../src/tieout/web
RUN mkdir -p ../src/tieout && npm run build

# --- python runtime ----------------------------------------------------------
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
COPY --from=web /app/src/tieout/web src/tieout/web
RUN pip install ".[server]" && rm -rf /app/src

RUN useradd --create-home --uid 10001 tieout && mkdir /data && chown tieout /data
USER tieout
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["tieout", "serve", "--host", "0.0.0.0", "--port", "8000", "--data", "/data"]
