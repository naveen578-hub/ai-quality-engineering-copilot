# Build context is expected to be the repo root (see docker-compose.yml).

# ---- Build stage ----
FROM node:20-slim AS build

WORKDIR /app

# package.json + package-lock.json copied separately from source so this
# layer (npm ci) is cached across code-only changes.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./
# VITE_API_BASE_URL is intentionally left unset here: with the nginx reverse
# proxy below, the frontend calls same-origin /api/... paths and never needs
# to know the backend's address directly. Override at build time
# (--build-arg) only if serving the frontend from a different origin than
# the one this nginx config proxies for.
RUN npm run build

# ---- Serve stage ----
FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1:80/ || exit 1
