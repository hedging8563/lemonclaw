# ============================================================
# LemonClaw - K8s Container Image
# ============================================================
# Multi-stage build: python3.12-slim + Node.js 20 (WhatsApp bridge)
# Target: ~500MB (vs OpenClaw 1.8GB)
#
# Build:
#   docker build -t ghcr.io/hedging8563/lemonclaw:latest -f deploy/k8s/Dockerfile .
# ============================================================

# Stage 1: Build WhatsApp bridge (Node.js)
FROM node:20-bookworm-slim AS bridge-builder

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && git config --global url."https://github.com/".insteadOf "ssh://git@github.com/" \
    && git config --global --add url."https://github.com/".insteadOf "git@github.com:"

WORKDIR /bridge
COPY bridge/package.json bridge/tsconfig.json ./
RUN npm install --production
COPY bridge/src ./src
# TypeScript compile if needed
RUN npx tsc --noEmit 2>/dev/null || true

# Stage 2: Runtime
FROM python:3.12-slim-bookworm

# tini: proper init process (reaps zombies, forwards signals)
# git: required by skill-installer to clone skill repos
# ffmpeg: required by yt-dlp for video/audio merging
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini \
    curl \
    git \
    ca-certificates \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Node.js 20 for WhatsApp bridge sidecar
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Chromium + agent-browser for browser automation (optional, ~400MB)
# Playwright installs Chromium and its system dependencies
RUN npx playwright install --with-deps chromium \
    && npm install -g agent-browser \
    && rm -rf /root/.cache/ms-playwright/.links \
    && rm -rf /tmp/* /root/.npm

# Create non-root user
RUN useradd -m -s /bin/bash lemonclaw

WORKDIR /app

# Install lemonclaw Python package
COPY pyproject.toml README.md LICENSE ./
COPY lemonclaw/ ./lemonclaw/
COPY bridge/ ./bridge/
RUN pip install --no-cache-dir . yt-dlp \
    && (pip cache purge 2>/dev/null || true)

# Overwrite bridge with compiled version from builder
COPY --from=bridge-builder /bridge /app/bridge

# Copy entrypoint
COPY deploy/k8s/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Health check (K8s probes also check, but this helps docker inspect)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -sf http://localhost:18789/health || exit 1

EXPOSE 18789

# tini as PID 1: forwards SIGTERM to lemonclaw, reaps zombie processes
ENTRYPOINT ["tini", "--"]
CMD ["/entrypoint.sh"]
