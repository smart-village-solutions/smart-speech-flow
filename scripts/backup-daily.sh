#!/bin/bash
# Daily backup script - runs at 00:00 UTC
# Retention: 7 days

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/backup-common.sh"

BACKUP_TYPE="daily"
RETENTION_DAYS=7

log_info "Starting daily backup..."

# Create backup directory
BACKUP_DIR=$(create_backup_dir "$BACKUP_TYPE")
log_info "Backup directory: $BACKUP_DIR"

# Perform backups
backup_grafana "$BACKUP_DIR"
backup_prometheus_recent "$BACKUP_DIR"
backup_loki_recent "$BACKUP_DIR"
backup_redis "$BACKUP_DIR"
backup_audio_files "$BACKUP_DIR"
backup_configs "$BACKUP_DIR"
backup_git_state "$BACKUP_DIR"

# Create summary
create_backup_summary "$BACKUP_DIR" "$BACKUP_TYPE"

# Verify backup
if verify_backup "$BACKUP_DIR"; then
    log_info "✅ Daily backup completed successfully"

    # Create 'latest' symlink
    ln -sfn "$BACKUP_DIR" "${BACKUP_ROOT}/${BACKUP_TYPE}/latest"

    # Cleanup old backups
    cleanup_old_backups "$BACKUP_TYPE" "$RETENTION_DAYS"
else
    log_error "❌ Daily backup verification failed"
    exit 1
fi
