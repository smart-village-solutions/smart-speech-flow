#!/bin/bash
# Monthly backup script - runs on 1st day at 02:00 UTC
# Retention: 12 months

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/backup-common.sh"

BACKUP_TYPE="monthly"
RETENTION_MONTHS=12

log_info "Starting monthly backup..."

# Create backup directory
BACKUP_DIR=$(create_backup_dir "$BACKUP_TYPE")
log_info "Backup directory: $BACKUP_DIR"

# Perform complete system backup
backup_complete_system "$BACKUP_DIR"
backup_git_archive "$BACKUP_DIR"
backup_documentation "$BACKUP_DIR"

# Create summary
create_backup_summary "$BACKUP_DIR" "$BACKUP_TYPE"

# Verify backup
if verify_backup "$BACKUP_DIR"; then
    log_info "✅ Monthly backup completed successfully"

    # Create 'latest' symlink
    ln -sfn "$BACKUP_DIR" "${BACKUP_ROOT}/${BACKUP_TYPE}/latest"

    # Cleanup old backups
    cleanup_old_backups "$BACKUP_TYPE" "$((RETENTION_MONTHS * 30))"
else
    log_error "❌ Monthly backup verification failed"
    exit 1
fi
