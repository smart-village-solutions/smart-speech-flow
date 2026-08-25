# Multi-stage Dockerfile for React SPA
# Stage 1: Build the application
FROM node:22-alpine AS builder

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies with peer-dependency compatibility, then restore the
# required esbuild binary explicitly after disabling install scripts.
RUN npm ci --legacy-peer-deps --ignore-scripts \
 && npm rebuild esbuild

# Copy only the files required for the SPA build
COPY src ./src
COPY public ./public
COPY index.html ./
COPY eslint.config.js ./
COPY tsconfig.app.json ./
COPY tsconfig.json ./
COPY tsconfig.node.json ./
COPY vite.config.ts ./

# Vite replaces these values while compiling the static SPA. Runtime
# environment variables in the Nginx container cannot change the bundle.
ARG VITE_API_BASE_URL
ARG VITE_WS_BASE_URL
# This value is intentionally public because Vite embeds it in browser code.
# It is a demo UI gate, not an authentication secret.
ARG VITE_DEMO_ACCESS_CODE

# Never produce a deployable image that sends browser traffic to localhost.
RUN if [ -z "${VITE_API_BASE_URL}" ] || [ -z "${VITE_WS_BASE_URL}" ]; then \
      echo >&2 "VITE_API_BASE_URL and VITE_WS_BASE_URL must be set"; \
      exit 1; \
    fi \
 && api_base_url_lower="$(printf '%s' "${VITE_API_BASE_URL}" | tr '[:upper:]' '[:lower:]')" \
 && ws_base_url_lower="$(printf '%s' "${VITE_WS_BASE_URL}" | tr '[:upper:]' '[:lower:]')" \
 && case "${api_base_url_lower}" in \
      *localhost*|*127.0.0.1*) echo >&2 "VITE_API_BASE_URL must not target localhost"; exit 1 ;; \
    esac \
 && case "${ws_base_url_lower}" in \
      *localhost*|*127.0.0.1*) echo >&2 "VITE_WS_BASE_URL must not target localhost"; exit 1 ;; \
    esac

# Build the application
RUN VITE_API_BASE_URL="${VITE_API_BASE_URL}" \
    VITE_WS_BASE_URL="${VITE_WS_BASE_URL}" \
    VITE_APP_PASSWORD="${VITE_DEMO_ACCESS_CODE}" \
    npm run build

# Stage 2: Serve with non-root Nginx
FROM nginxinc/nginx-unprivileged:alpine

# Copy custom nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built files from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Expose non-privileged port
EXPOSE 8080

# Health check (use IPv4 explicitly)
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:8080/health || exit 1

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
