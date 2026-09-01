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
| ClickHouse | 8123 (public) | `expose: 8123` (internal) | Via authenticated Compose exec only |
| Keycloak PostgreSQL | 5432 (public) | No host port or Traefik route | Via Keycloak on the Compose network only |

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
- [ ] Generate a ClickHouse password: `openssl rand -base64 32`
- [ ] Set `CLICKHOUSE_DB`, `CLICKHOUSE_USER`, and `CLICKHOUSE_PASSWORD` in `.env`
- [ ] Generate Keycloak database and bootstrap-admin passwords: `openssl rand -base64 32`
- [ ] Set the six required `KEYCLOAK_*` variables in `.env`, including the non-secret `KEYCLOAK_HOSTNAME`
- [ ] Review all other environment variables in `.env`

### Security Verification

```bash
# 1. Check that monitoring ports are NOT exposed to host
docker compose config | grep -A 5 "prometheus:"
docker compose config | grep -A 5 "loki:"
docker compose config | grep -A 5 "cadvisor:"
docker compose config | grep -A 5 "ollama:"
docker compose config | grep -A 20 "clickhouse:"

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
- ClickHouse is internal-only on `clickhouse:8123`; it has no `ports` entry,
  no Traefik labels, and no public SQL UI. Its credentials are required through
  `.env`; never enable `CLICKHOUSE_SKIP_USER_SETUP`.

For start-up, verification, backup, restore, upgrade, rollback, and incident
procedures, see the [ClickHouse Operations Runbook](../operations/runbooks/clickhouse-operations.md).

Keycloak is public only through Traefik at the deployment-specific `KEYCLOAK_HOSTNAME`;
its PostgreSQL database and management endpoint have no public route. See the
[Keycloak Operations Runbook](../operations/runbooks/keycloak-operations.md).

## Default Passwords

### ⚠️ Frontend Demo Access Code

The frontend uses a client-visible demo access code for the landing page:
- **Configuration:** Set in `.env` using the legacy variable name `FRONTEND_DEMO_PASSWORD`
- **Default:** `ssf2025kassel`
- **Docker:** `FRONTEND_DEMO_PASSWORD` is mapped to the intentionally public `VITE_DEMO_ACCESS_CODE` build argument and then embedded in the browser bundle
- **Security:** Client-side only, with no backend validation; never treat it as authentication or authorization
- **Production:** Customize it if desired, but enforce access restrictions through server-side authentication

The Keycloak infrastructure does not yet replace this demo gate. SSF login and
authorization integration require a separate approved change.

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
