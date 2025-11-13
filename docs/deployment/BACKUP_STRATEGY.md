# Backup Strategy - Smart Speech Flow Backend

## Disk Space Analysis

**Available Space:** 1.4TB free (18% used of 1.7TB total)

**Current Data Sizes:**
- Monitoring (Grafana, Prometheus, Loki): 43MB
- Audio data: 6.6MB
- Models: 4KB
- Docker images: ~2.5GB (multiple layers)

**Backup Space Requirements:**
- Daily backups (7 days): ~500MB
- Weekly backups (4 weeks): ~200MB
- Monthly backups (12 months): ~600MB
- **Total estimated:** ~1.3GB (plenty of headroom)

---

## Backup Components

### 1. Critical Data (Daily)
- Grafana database & dashboards
- Prometheus data (metrics)
- Loki logs
- Redis data
- Configuration files (.env, docker-compose.yml)

### 2. Application State (Daily)
- Audio files (original + translated)
- Session metadata
- Circuit breaker states

### 3. System Configuration (Weekly)
- Docker volumes
- Traefik certificates
- Alert rules & monitoring configs

### 4. Models (One-time + updates)
- ASR models
- Translation models
- TTS models

---

## Backup Schedule

### Daily Backups (00:00 UTC)
```bash
# Run: /root/projects/ssf-backend/scripts/backup-daily.sh
# Retention: 7 days
# Estimated size: 50-100MB per backup
```

**Contents:**
- Grafana database (SQLite)
- Prometheus TSDB (last 24h)
- Loki chunks (last 24h)
- Redis dump
- Audio files (if retention > 24h)
- Configuration files

### Weekly Backups (Sunday 01:00 UTC)
```bash
# Run: /root/projects/ssf-backend/scripts/backup-weekly.sh
# Retention: 4 weeks
# Estimated size: 100-200MB per backup
```

**Contents:**
- Full Prometheus TSDB
- Full Loki chunks
- Docker volumes (grafana, prometheus, loki)
- All configuration files
- Git repository state (commit hash, branch)

### Monthly Backups (1st day 02:00 UTC)
```bash
# Run: /root/projects/ssf-backend/scripts/backup-monthly.sh
# Retention: 12 months
# Estimated size: 200-300MB per backup
```

**Contents:**
- Complete system snapshot
- All Docker volumes
- All configuration files
- Git repository archive
- Documentation state

---

## Backup Locations

### Local Backups (Primary)
```
/root/projects/ssf-backend/backups/
├── daily/          # 7 days retention
│   ├── 20251113_000000/
│   ├── 20251112_000000/
│   └── ...
├── weekly/         # 4 weeks retention
│   ├── 20251110_010000/
│   └── ...
├── monthly/        # 12 months retention
│   ├── 202511_020000/
│   └── ...
└── restore/        # Staging area for restores
```

### Remote Backups (Optional)
- S3-compatible storage (Minio, AWS S3, Backblaze B2)
- SFTP/rsync to external server
- Encrypted cloud backup

---

## Backup Scripts

### 1. Daily Backup Script
```bash
#!/bin/bash
# scripts/backup-daily.sh

set -e
source "$(dirname "$0")/backup-common.sh"

BACKUP_TYPE="daily"
RETENTION_DAYS=7

backup_grafana
backup_prometheus_recent
backup_loki_recent
backup_redis
backup_audio_files
backup_configs
cleanup_old_backups "$BACKUP_TYPE" "$RETENTION_DAYS"
```

### 2. Weekly Backup Script
```bash
#!/bin/bash
# scripts/backup-weekly.sh

set -e
source "$(dirname "$0")/backup-common.sh"

BACKUP_TYPE="weekly"
RETENTION_WEEKS=4

backup_grafana
backup_prometheus_full
backup_loki_full
backup_docker_volumes
backup_configs
backup_git_state
cleanup_old_backups "$BACKUP_TYPE" "$((RETENTION_WEEKS * 7))"
```

### 3. Monthly Backup Script
```bash
#!/bin/bash
# scripts/backup-monthly.sh

set -e
source "$(dirname "$0")/backup-common.sh"

BACKUP_TYPE="monthly"
RETENTION_MONTHS=12

backup_complete_system
backup_git_archive
backup_documentation
cleanup_old_backups "$BACKUP_TYPE" "$((RETENTION_MONTHS * 30))"
```

---

## Automated Scheduling (Cron)

Add to root crontab:
```cron
# Smart Speech Flow Backups
0 0 * * * /root/projects/ssf-backend/scripts/backup-daily.sh >> /var/log/ssf-backup-daily.log 2>&1
0 1 * * 0 /root/projects/ssf-backend/scripts/backup-weekly.sh >> /var/log/ssf-backup-weekly.log 2>&1
0 2 1 * * /root/projects/ssf-backend/scripts/backup-monthly.sh >> /var/log/ssf-backup-monthly.log 2>&1
```

Or use systemd timers:
```bash
# Install timers
sudo systemctl enable --now ssf-backup-daily.timer
sudo systemctl enable --now ssf-backup-weekly.timer
sudo systemctl enable --now ssf-backup-monthly.timer
```

---

## Restore Procedures

### Quick Restore (Grafana Example)
```bash
# 1. List available backups
ls -lh backups/daily/

# 2. Stop service
docker compose stop grafana

# 3. Restore database
./scripts/restore-grafana.sh backups/daily/20251113_000000

# 4. Start service
docker compose up -d grafana

# 5. Verify
curl -u "admin:${GRAFANA_ADMIN_PASSWORD}" http://localhost:3000/api/user
```

### Full System Restore
```bash
# 1. Stop all services
docker compose down

# 2. Restore from backup
./scripts/restore-full.sh backups/monthly/202511_020000

# 3. Verify configurations
docker compose config --quiet

# 4. Start services
docker compose up -d

# 5. Verify health
./scripts/health-check.sh
```

---

## Backup Verification

### Automated Tests (Daily)
```bash
#!/bin/bash
# scripts/verify-backups.sh

# Test backup integrity
tar -tzf backups/daily/latest/grafana.tar.gz > /dev/null
tar -tzf backups/daily/latest/prometheus.tar.gz > /dev/null

# Test restore (dry-run)
./scripts/restore-grafana.sh --dry-run backups/daily/latest

# Verify backup size (should be > 10MB)
SIZE=$(du -sm backups/daily/latest | cut -f1)
if [ "$SIZE" -lt 10 ]; then
    echo "❌ Backup too small: ${SIZE}MB"
    exit 1
fi

echo "✅ Backup verification passed"
```

---

## Monitoring & Alerts

### Backup Success Metrics
- Prometheus metrics: `ssf_backup_success{type="daily|weekly|monthly"}`
- Grafana dashboard: "Backup Status"
- Alert: Backup failed or size anomaly

### Disk Space Monitoring
```yaml
# Alert when backup disk usage > 80%
- alert: BackupDiskSpaceHigh
  expr: (1 - (node_filesystem_avail_bytes{mountpoint="/root"} / node_filesystem_size_bytes{mountpoint="/root"})) > 0.8
  for: 5m
  annotations:
    summary: "Backup disk space high ({{ $value | humanizePercentage }})"
```

---

## Security Considerations

### Backup Encryption (Optional)
```bash
# Encrypt backups with GPG
tar czf - backups/daily/20251113_000000/ | \
    gpg --symmetric --cipher-algo AES256 > \
    backups/daily/20251113_000000.tar.gz.gpg
```

### Access Control
```bash
# Restrict backup directory permissions
chmod 700 /root/projects/ssf-backend/backups
chown -R root:root /root/projects/ssf-backend/backups
```

### Sensitive Data
- Exclude `.env` from remote backups (contains passwords)
- Encrypt backups before uploading to cloud
- Use separate encryption keys for each backup type

---

## Disaster Recovery Plan

### RTO (Recovery Time Objective)
- Critical services (API Gateway): 15 minutes
- Monitoring (Grafana): 30 minutes
- Full system: 1 hour

### RPO (Recovery Point Objective)
- Critical data: 24 hours (daily backup)
- Configuration: 7 days (weekly backup)
- Historical data: 30 days (monthly backup)

### Recovery Steps
1. Provision new server (if hardware failure)
2. Install Docker & Docker Compose
3. Clone repository: `git clone https://github.com/smart-village-solutions/smart-speech-flow.git`
4. Restore latest backup: `./scripts/restore-full.sh backups/daily/latest`
5. Update DNS (if IP changed)
6. Verify all services: `./scripts/health-check.sh`
7. Monitor for 24 hours

---

## Testing Schedule

- **Daily:** Verify backup completion (automated)
- **Weekly:** Test Grafana restore (manual)
- **Monthly:** Full disaster recovery drill (manual)
- **Quarterly:** Off-site restore test (manual)

---

## Backup Checklist

Before Production:
- [ ] Install backup scripts
- [ ] Configure cron jobs
- [ ] Test daily backup
- [ ] Test restore procedure
- [ ] Set up monitoring alerts
- [ ] Document backup locations
- [ ] Train team on restore procedures

After Production:
- [ ] Monitor backup success rate (should be 100%)
- [ ] Review backup sizes (watch for anomalies)
- [ ] Test restore monthly
- [ ] Review retention policies quarterly
- [ ] Audit backup security annually
