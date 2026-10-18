# 1) web kliens építése
FROM node:22-slim AS web
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# 2) szerver
FROM python:3.12-slim
# deno: a yt-dlp-nek JS futtató kell a YouTube aláírások feloldásához
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server/app ./app
COPY --from=web /web/dist ./web_dist
ENV DATA_DIR=/data WEB_DIR=/srv/web_dist PORT=8080
VOLUME /data
EXPOSE 8080
CMD ["python", "-m", "app"]
