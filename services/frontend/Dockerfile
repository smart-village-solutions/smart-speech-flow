# Multi-stage Dockerfile for React SPA
# Stage 1: Build the application
FROM node:20-alpine AS builder

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
COPY postcss.config.js ./
COPY tailwind.config.js ./
COPY tsconfig.app.json ./
COPY tsconfig.json ./
COPY tsconfig.node.json ./
COPY vite.config.ts ./

# Build the application
RUN npm run build

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
