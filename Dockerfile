# Stage 1: Build React frontend
FROM node:20-slim AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Production image
FROM python:3.12-slim

# Chromium & Firefox (Camoufox) system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdbus-1-3 libdrm2 libxkbcommon0 libatspi2.0-0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libx11-xcb1 libfontconfig1 libx11-6 \
    libxcb1 libxext6 libxshmfence1 \
    libglib2.0-0 libgtk-3-0 libpangocairo-1.0-0 libcairo-gobject2 \
    libgdk-pixbuf-2.0-0 libxss1 libxtst6 fonts-liberation \
    libgl1-mesa-dri libegl-mesa0 \
    libdbus-glib-1-2 libxt6 libpci3 \
    procps wget ca-certificates xclip \
    && rm -rf /var/lib/apt/lists/*

# Playwright system deps (chromium & firefox)
RUN pip install --no-cache-dir playwright && playwright install-deps chromium firefox 2>/dev/null || true && pip uninstall -y playwright

# Windows core fonts (Arial, Times New Roman, Verdana, etc.)
RUN echo "deb http://deb.debian.org/debian trixie contrib" >> /etc/apt/sources.list.d/contrib.list \
    && echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections \
    && apt-get update && apt-get install -y --no-install-recommends ttf-mscorefonts-installer \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

# Install KasmVNC (auto-selects amd64 or arm64 based on build platform)
ARG TARGETARCH
RUN wget -q https://github.com/kasmtech/KasmVNC/releases/download/v1.3.3/kasmvncserver_bookworm_1.3.3_${TARGETARCH}.deb \
    && apt-get update && apt-get install -y -f ./kasmvncserver_bookworm_1.3.3_${TARGETARCH}.deb \
    && rm kasmvncserver_bookworm_1.3.3_${TARGETARCH}.deb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps via uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./
RUN uv export --no-dev --frozen --output-file /tmp/requirements.txt \
    && uv pip install --system --no-cache -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Backend code
COPY backend/ /app/backend/

# Frontend build from stage 1
COPY --from=frontend-builder /build/dist /app/frontend/dist

# Pre-download CloakBrowser binary
RUN python -c "from cloakbrowser.download import ensure_binary; ensure_binary()"

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health')" || exit 1

VOLUME /data

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
