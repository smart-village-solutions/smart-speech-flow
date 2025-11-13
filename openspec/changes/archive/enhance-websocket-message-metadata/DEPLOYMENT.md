# Deployment Guide: WebSocket Metadata Enhancement

## Deployment Risiken & Mitigation

### 1. Volume Mount Risiken

#### Problem: Volume voll
```yaml
# RISIKO: Wenn ./data/audio voll ist, können keine neuen Dateien gespeichert werden
volumes:
  - ./data/audio:/data/audio
```

**Symptome:**
- `OSError: [Errno 28] No space left on device`
- Audio-Upload schlägt fehl
- Cleanup-Job kann keine neuen Files löschen

**Mitigation:**
1. **Prometheus Alerts** (bereits konfiguriert):
   ```yaml
   # monitoring/alert_rules.yml
   - alert: AudioStorageDiskUsageHigh
     expr: audio_storage_disk_usage_bytes / 10737418240 > 0.8
     annotations:
       summary: "Audio storage >80% full"

   - alert: AudioStorageDiskUsageCritical
     expr: audio_storage_disk_usage_bytes / 10737418240 > 0.95
     annotations:
       summary: "Audio storage >95% full - CRITICAL"
   ```

2. **Disk Space Monitoring:**
   ```bash
   # Regelmäßig prüfen
   docker exec api_gateway df -h /data/audio

   # Alert bei >80%
   USAGE=$(docker exec api_gateway df /data/audio | awk 'NR==2 {print $5}' | sed 's/%//')
   if [ $USAGE -gt 80 ]; then
     echo "WARNING: Audio storage at ${USAGE}%"
   fi
   ```

3. **Manuelle Notfall-Bereinigung:**
   ```bash
   # Notfall: Alle Files >12h löschen (statt 24h)
   docker exec api_gateway find /data/audio -type f -mmin +720 -delete

   # Oder: Älteste 50% der Files löschen
   docker exec api_gateway bash -c 'cd /data/audio/original && ls -t | tail -n $(($(ls | wc -l) / 2)) | xargs rm -f'
   ```

#### Problem: Volume Backup
```yaml
# RISIKO: Bei Docker-Neustart bleiben alte Files - Kein automatisches Backup
volumes:
  - ./data/audio:/data/audio
```

**Empfehlung:**
```yaml
# docker-compose.yml - IMPROVED VERSION
services:
  api_gateway:
    volumes:
      # Explizite Bind Mount-Konfiguration
      - type: bind
        source: ./data/audio
        target: /data/audio
        bind:
          create_host_path: true

      # Separates Volume für temporäre Uploads
      - audio_temp:/tmp/audio

volumes:
  audio_temp:
    driver: local
    driver_opts:
      type: tmpfs
      device: tmpfs
      o: size=1G,uid=1000,gid=1000
```

**Vorteile:**
- `audio_temp` in RAM → schneller, kein Disk-Spam
- Bei Container-Neustart wird temp automatisch geleert
- Produktions-Audio in `./data/audio` bleibt persistent

**Backup-Strategie:**
```bash
#!/bin/bash
# backup_audio.sh - Läuft täglich via Cron

DATE=$(date +%Y%m%d)
BACKUP_DIR="/backup/audio/${DATE}"

# Backup nur wenn Files vorhanden
if [ "$(ls -A ./data/audio/original)" ]; then
  mkdir -p "${BACKUP_DIR}"
  rsync -av --delete ./data/audio/ "${BACKUP_DIR}/"

  # Alte Backups löschen (>7 Tage)
  find /backup/audio -type d -mtime +7 -exec rm -rf {} \;
fi
```

**WICHTIG:** Audio-Backups sind DSGVO-kritisch!
- Retention-Policy gilt auch für Backups
- Backups nach 24h ebenfalls löschen
- Oder: Backups nur für Disaster Recovery (verschlüsselt, restricted access)

### 2. Docker Configuration - Production-Ready

#### Empfohlene docker-compose.yml

```yaml
version: '3.8'

services:
  api_gateway:
    build:
      context: ./services/api_gateway
      dockerfile: Dockerfile

    # Resource Limits (verhindert OOM bei vielen Audio-Files)
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '1.0'
          memory: 1G

    environment:
      # Audio Storage Configuration
      AUDIO_STORAGE_PATH: /data/audio
      AUDIO_RETENTION_HOURS: 24
      AUDIO_TEMP_PATH: /tmp/audio

      # Disk Space Limits (fail early wenn voll)
      AUDIO_MAX_DISK_USAGE_GB: 9  # 90% von 10GB

      # Performance Tuning
      ENABLE_PIPELINE_METADATA: "true"
      AUDIO_CLEANUP_INTERVAL_MINUTES: 60

    volumes:
      # Persistent Audio Storage
      - type: bind
        source: ./data/audio
        target: /data/audio
        bind:
          create_host_path: true

      # Temporary Upload Buffer (RAM)
      - type: tmpfs
        target: /tmp/audio
        tmpfs:
          size: 1G
          mode: 1777

    # Health Checks
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

    # Logging (wichtig für Debugging)
    logging:
      driver: "json-file"
      options:
        max-size: "100m"
        max-file: "5"

    ports:
      - "8000:8000"

    networks:
      - backend

networks:
  backend:
    driver: bridge
```

### 3. Pre-Deployment Checklist

#### Storage Preparation
```bash
# 1. Erstelle Audio-Verzeichnisse
mkdir -p ./data/audio/original
mkdir -p ./data/audio/translated

# 2. Setze Permissions (wichtig für Docker)
chmod -R 755 ./data/audio
chown -R 1000:1000 ./data/audio  # UID/GID des Container-Users

# 3. Prüfe verfügbaren Speicherplatz
df -h ./data/audio
# MINIMUM: 10GB frei

# 4. Test-Write
touch ./data/audio/.test && rm ./data/audio/.test
echo "✅ Write permission OK"
```

#### Monitoring Setup
```bash
# 1. Grafana Dashboard importieren
curl -X POST http://localhost:3000/api/dashboards/db \
  -H "Content-Type: application/json" \
  -d @monitoring/grafana/dashboards/audio-storage-pipeline.json

# 2. Prometheus Alerts aktivieren
docker-compose restart prometheus

# 3. Verify Metrics Endpoint
curl http://localhost:8000/metrics | grep audio_storage
```

### 4. Deployment Steps

#### Option A: Rolling Update (Zero Downtime)
```bash
# 1. Build new image
docker-compose build api_gateway

# 2. Tag image
docker tag ssf-backend_api_gateway:latest ssf-backend_api_gateway:v1.1.0

# 3. Deploy new container (parallel zu altem)
docker-compose up -d --no-deps --scale api_gateway=2 api_gateway

# 4. Health check auf neuer Instance
sleep 10
docker ps | grep api_gateway
curl http://localhost:8001/health  # Neuer Port

# 5. Stop old container
docker-compose up -d --no-deps --scale api_gateway=1 api_gateway

# 6. Verify
curl http://localhost:8000/metrics | grep audio_storage
```

#### Option B: Simple Update (kurzer Downtime)
```bash
# 1. Build and deploy
docker-compose up -d --build api_gateway

# 2. Verify
docker-compose logs -f api_gateway | grep "Audio storage initialized"
curl http://localhost:8000/health
```

### 5. Post-Deployment Verification

```bash
#!/bin/bash
# verify_deployment.sh

echo "=== Audio Storage Verification ==="

# 1. Check volumes
echo "1. Volume mounts:"
docker inspect api_gateway | jq '.[0].Mounts'

# 2. Check disk space
echo -e "\n2. Disk space:"
docker exec api_gateway df -h /data/audio

# 3. Test audio save/retrieve
echo -e "\n3. Testing audio storage..."
TEST_FILE="/tmp/test_audio.wav"
echo "test audio data" > $TEST_FILE

# Upload test audio (requires session)
SESSION_ID=$(curl -s -X POST http://localhost:8000/api/session \
  -H "Content-Type: application/json" \
  -d '{"source_language":"en","target_language":"de"}' | jq -r '.session_id')

echo "Created test session: $SESSION_ID"

# 4. Check Prometheus metrics
echo -e "\n4. Prometheus metrics:"
curl -s http://localhost:8000/metrics | grep audio_storage_disk_usage_bytes
curl -s http://localhost:8000/metrics | grep audio_files_total

# 5. Check cleanup job
echo -e "\n5. Cleanup job status:"
docker exec api_gateway ps aux | grep cleanup || echo "Background task running"

# 6. Check Grafana dashboard
echo -e "\n6. Grafana dashboard:"
curl -s http://localhost:3000/api/dashboards/uid/audio-storage-pipeline | jq '.dashboard.title'

echo -e "\n✅ Deployment verification complete"
```

### 6. Rollback Procedure

#### Full Rollback
```bash
# 1. Revert to previous image
docker-compose down
docker tag ssf-backend_api_gateway:v1.0.0 ssf-backend_api_gateway:latest
docker-compose up -d api_gateway

# 2. Verify rollback
curl http://localhost:8000/health
```

#### Audio-Only Rollback (keep metadata)
```bash
# Stop cleanup job, disable audio storage
docker exec api_gateway pkill -f cleanup_audio
docker-compose exec api_gateway bash -c 'echo "ENABLE_AUDIO_STORAGE=false" >> .env'
docker-compose restart api_gateway
```

### 7. Monitoring & Alerts

#### Critical Metrics to Watch (First 24h)
```bash
# 1. Disk usage growth rate
watch -n 60 'docker exec api_gateway du -sh /data/audio/*'

# 2. File count
watch -n 300 'docker exec api_gateway find /data/audio -type f | wc -l'

# 3. Memory usage (check for leaks)
watch -n 60 'docker stats api_gateway --no-stream'

# 4. Cleanup job execution
docker-compose logs -f api_gateway | grep "cleanup"
```

#### Alert Integration
```yaml
# monitoring/alert_rules.yml (bereits konfiguriert)
groups:
  - name: audio_storage
    interval: 60s
    rules:
      - alert: AudioStorageDiskUsageHigh
        expr: audio_storage_disk_usage_bytes / 10737418240 > 0.8
        for: 5m
        annotations:
          summary: "Audio storage disk usage high (>80%)"
          description: "Current usage: {{ $value | humanize }}%"

      - alert: AudioCleanupFailures
        expr: increase(audio_cleanup_errors_total[1h]) > 0
        annotations:
          summary: "Audio cleanup job failures detected"
```

### 8. Disaster Recovery

#### Scenario: Volume corrupted
```bash
# 1. Stop services
docker-compose down

# 2. Backup corrupted volume
mv ./data/audio ./data/audio.corrupted.$(date +%s)

# 3. Restore from backup (if available)
rsync -av /backup/audio/latest/ ./data/audio/

# 4. Or: Start fresh
mkdir -p ./data/audio/{original,translated}
chmod -R 755 ./data/audio

# 5. Restart services
docker-compose up -d api_gateway
```

#### Scenario: Disk full, can't cleanup
```bash
# Emergency: Manually delete oldest files
docker exec api_gateway bash -c '
  cd /data/audio/original &&
  ls -t | tail -n 100 | xargs rm -f
'

# Verify space
docker exec api_gateway df -h /data/audio

# Restart cleanup job
docker-compose restart api_gateway
```

## Production Checklist

Before deploying to production:

- [ ] Disk space: Minimum 10GB free in `./data/audio`
- [ ] Permissions: `./data/audio` writable by UID 1000
- [ ] Resource limits: 2GB RAM, 2 CPU cores allocated
- [ ] Monitoring: Grafana dashboard accessible
- [ ] Alerts: Prometheus alerts configured and tested
- [ ] Backups: Backup strategy defined (if applicable)
- [ ] Health checks: `/health` endpoint responds
- [ ] Metrics: `/metrics` shows `audio_storage_*` metrics
- [ ] Cleanup job: Verified running via `docker logs`
- [ ] DSGVO compliance: 24h retention documented and enforced

## Support

For deployment issues:
1. Check logs: `docker-compose logs -f api_gateway`
2. Check metrics: `curl http://localhost:8000/metrics | grep audio`
3. Check disk: `docker exec api_gateway df -h /data/audio`
4. Review alerts: Grafana dashboard

---

**Last Updated:** 2025-11-06
**Version:** 1.1.0
