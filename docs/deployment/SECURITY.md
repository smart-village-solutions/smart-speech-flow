# Security Configuration

## Overview

This document describes the security configuration for production deployments of the Smart Speech Flow Backend.

## Changes from Default Configuration

### 🔒 Monitoring Services Security (2024-11-13)

**Critical security improvements implemented before public launch:**

#### 1. Grafana Credentials
- **Old:** Hardcoded `admin/admin` (INSECURE)
- **New:** Environment variables with strong password requirement
- **Action Required:** Set `GRAFANA_ADMIN_PASSWORD` in production `.env`

```bash
# Generate strong password
openssl rand -base64 32

# Set in .env file
GRAFANA_ADMIN_PASSWORD=your_generated_password_here
```

#### 2. Internal-Only Services

The following services are now **only accessible within Docker network** (not exposed to host):

| Service | Old Port | New Configuration | Access Method |
|---------|----------|-------------------|---------------|
| Prometheus | 9090 (public) | `expose: 9090` (internal) | Via Grafana or Traefik |
| Loki | 3100 (public) | `expose: 3100` (internal) | Via Grafana |
| cAdvisor | 8080 (public) | `expose: 8080` (internal) | Via Prometheus |
| Ollama | 11434 (public) | `expose: 11434` (internal) | Via API Gateway |

**Benefits:**
- ✅ No direct public access to metrics
- ✅ Reduced attack surface
- ✅ Internal communication still works
- ✅ Grafana can still query all data sources

#### 3. Traefik Dashboard
- **Old:** `--api.insecure=true` (public dashboard on port 8080)
- **New:** `--api.dashboard=true` (dashboard available but not publicly exposed)
- **Access:** Only via Traefik labels (can be configured with Basic Auth)

## Production Checklist

### Before First Deployment

- [ ] Copy `.env.example` to `.env`
- [ ] Generate strong Grafana password: `openssl rand -base64 32`
- [ ] Set `GRAFANA_ADMIN_PASSWORD` in `.env`
- [ ] Verify `GRAFANA_ADMIN_USER` (default: `admin`)
- [ ] Review all other environment variables in `.env`

### Security Verification

```bash
# 1. Check that monitoring ports are NOT exposed to host
docker compose config | grep -A 5 "prometheus:"
docker compose config | grep -A 5 "loki:"
docker compose config | grep -A 5 "cadvisor:"
docker compose config | grep -A 5 "ollama:"

# 2. Verify Grafana uses environment variables
docker compose config | grep -A 10 "grafana:" | grep GRAFANA

# 3. Test Grafana login with your new password
curl -u "admin:YOUR_PASSWORD" http://localhost:3000/api/health
```

## Architecture Security

### Network Isolation

```
┌─────────────────────────────────────────────────────┐
│ Public Internet                                      │
└────────────────┬────────────────────────────────────┘
                 │
                 ▼
         ┌──────────────┐
         │   Traefik    │ (Ports 80, 443)
         │ (HTTPS/WSS)  │
         └──────┬───────┘
                │
    ┌───────────┼───────────────┐
    │           │               │
    ▼           ▼               ▼
┌────────┐  ┌──────┐      ┌─────────┐
│ API    │  │Grafana│      │Frontend │
│Gateway │  │:3000  │      │  :80    │
└────┬───┘  └───┬──┘      └─────────┘
     │          │
     │   Docker Network (Internal Only)
     │          │
     ├──────────┼───────────────────┐
     ▼          ▼                   ▼
┌─────────┐ ┌──────────┐    ┌──────────┐
│Prometheus│ │  Loki    │    │ Ollama   │
│  :9090   │ │  :3100   │    │  :11434  │
└─────────┘ └──────────┘    └──────────┘
```

**Key Points:**
- Only Traefik, API Gateway, Grafana, and Frontend expose ports to host
- All monitoring services communicate internally via Docker network
- Grafana accesses Prometheus/Loki via internal DNS (`prometheus:9090`, `loki:3100`)
- API Gateway accesses Ollama via internal DNS (`ollama:11434`)

## Default Passwords

### ⚠️ Frontend Demo Password

The frontend uses a demo password for the landing page:
- **Password:** `ssf2025kassel`
- **Location:** `services/frontend/.env.production`
- **Security:** Client-side only, no backend validation
- **Production:** Change via `VITE_APP_PASSWORD` environment variable

### ✅ Grafana Admin Password

- **Default:** `admin/admin` (development only)
- **Production:** **MUST** be changed via environment variable
- **Enforcement:** Application will prompt for password change on first login

## Incident Response

### If Default Passwords Were Used in Production

1. **Immediate Actions:**
   ```bash
   # Stop services
   docker compose down

   # Set strong password
   echo "GRAFANA_ADMIN_PASSWORD=$(openssl rand -base64 32)" >> .env

   # Restart with new password
   docker compose up -d
   ```

2. **Verify Security:**
   - Check Grafana logs for unauthorized access
   - Review Prometheus query logs
   - Audit container access logs

3. **Long-term:**
   - Rotate all credentials
   - Review security audit logs
   - Document incident in security log

## Security Updates

| Date | Change | Severity | Status |
|------|--------|----------|--------|
| 2024-11-13 | Grafana password from environment | Critical | ✅ Fixed |
| 2024-11-13 | Internal-only monitoring services | High | ✅ Fixed |
| 2024-11-13 | Traefik dashboard secured | Medium | ✅ Fixed |

## References

- [Docker Compose Networking](https://docs.docker.com/compose/networking/)
- [Grafana Security](https://grafana.com/docs/grafana/latest/setup-grafana/configure-security/)
- [Traefik Security](https://doc.traefik.io/traefik/operations/api/)
- [OWASP Docker Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html)
