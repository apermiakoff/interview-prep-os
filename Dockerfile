FROM node:22-alpine AS web
WORKDIR /src
COPY package.json package-lock.json* ./
RUN npm install
COPY tsconfig*.json vite.config.ts ./
COPY frontend ./frontend
RUN npm run build

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    INTERVIEW_PREP_DB=/data/interview-prep.db \
    INTERVIEW_PREP_STATIC=/app/frontend/dist
WORKDIR /app
RUN groupadd --gid 1000 app && useradd --uid 1000 --gid 1000 --home /app app
COPY pyproject.toml uv.lock* ./
RUN pip install --no-cache-dir uv && uv sync --no-dev --frozen || uv sync --no-dev
COPY app ./app
COPY scripts ./scripts
COPY --from=web /src/frontend/dist ./frontend/dist
RUN mkdir -p /data && chown -R app:app /app /data
USER app
EXPOSE 8000
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
