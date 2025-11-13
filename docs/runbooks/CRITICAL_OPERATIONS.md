# Critical Operations Checklist

## Before Deleting or Resetting Data

**ALWAYS** follow this checklist before performing destructive operations:

### 1. Identify What Will Be Lost
- [ ] List all data that will be deleted
- [ ] Check if data is backed up
- [ ] Verify if data can be recovered

### 2. Create Backup
```bash
# For Grafana
./scripts/backup-grafana.sh

# For databases
docker compose exec <service> <backup-command>
```

### 3. Export Critical Configurations
- [ ] Export dashboards (Grafana API)
- [ ] Export alerts and rules
- [ ] Export data sources configuration

### 4. Document Current State
```bash
# Take snapshots of current configuration
docker compose exec grafana grafana-cli admin data-migration extract
```

### 5. Verify Backup
- [ ] Check backup files exist
- [ ] Verify backup is readable
- [ ] Test restore procedure (if possible)

### 6. Get User Confirmation
- [ ] Warn user about data loss
- [ ] List what will be deleted
- [ ] Ask for explicit confirmation
- [ ] Suggest alternatives

## Alternatives to Data Deletion

### Password Reset
Instead of deleting database:
```bash
# Reset Grafana password without losing data
docker compose exec grafana grafana-cli admin reset-admin-password <new-password>
```

### Database Surgery
```bash
# Modify SQLite database directly
docker compose exec grafana sqlite3 /var/lib/grafana/grafana.db \
  "UPDATE user SET password='<hashed-password>' WHERE login='admin';"
```

### Volume Snapshots
```bash
# Create Docker volume snapshot before changes
docker run --rm -v ssf-backend_grafana_data:/data -v $(pwd)/backups:/backup \
  alpine tar czf /backup/grafana-volume-$(date +%s).tar.gz /data
```

## Recovery Procedures

### Restore from Backup
```bash
# Stop service
docker compose stop grafana

# Restore database
cp -r backups/grafana/<timestamp>/database/* ./monitoring/grafana/

# Start service
docker compose up -d grafana
```

### Import Dashboards
```bash
# Via API
for file in backups/grafana/*/dashboards/*.json; do
  curl -X POST -H "Content-Type: application/json" \
    -u "admin:${PASSWORD}" \
    -d @"${file}" \
    http://localhost:3000/api/dashboards/db
done
```

## Lessons Learned

1. **Never assume data can be recreated** - Always backup first
2. **Explore non-destructive solutions** - Try password reset before database reset
3. **Communicate impact clearly** - User must understand what will be lost
4. **Test in isolation** - Use docker volumes to test destructive operations
5. **Document everything** - Keep notes of what was done and why

## Red Flags - Stop and Think

🚨 **STOP** if you're about to:
- Delete a directory with `rm -rf`
- Drop a database
- Reset a container with data volumes
- Overwrite configuration files

✅ **INSTEAD**:
1. Create backup
2. List alternatives
3. Get confirmation
4. Document decision
5. Proceed with caution
