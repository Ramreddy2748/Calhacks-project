FROM node:22.14-bookworm-slim AS dashboard
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --legacy-peer-deps --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATABASE_PATH=/data/holdon.sqlite3 HOLDON_REQUIRE_AUTH=1
WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt && useradd --uid 10001 --create-home holdon && mkdir /data && chown holdon:holdon /data
COPY backend/app ./backend/app
COPY --from=dashboard /build/dist ./frontend/dist
USER holdon
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
