FROM node:22-alpine AS frontend
WORKDIR /ui
RUN npm install --global pnpm@11.25.0
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home support && mkdir -p /data/uploads && chown -R support:support /data
COPY backend/ ./
COPY --from=frontend /ui/dist ./app/static
USER support
EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--workers","1","--ws-max-size","16384","--proxy-headers","--forwarded-allow-ips","*"]
