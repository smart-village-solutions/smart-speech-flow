#!/bin/bash
# Verify backup integrity and send alerts if needed

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/backup-common.sh"

ERRORS=0

log_info "Verifying backups..."

# Check daily backup
if [ -d "${BACKUP_ROOT}/daily/latest" ]; then
    if verify_backup "${BACKUP_ROOT}/daily/latest"; then
        log_info "✅ Daily backup OK"
    else
        log_error "❌ Daily backup verification failed"
        ((ERRORS++))
    fi
else
    log_error "❌ No daily backup found"
    ((ERRORS++))
fi

# Check weekly backup (if exists)
if [ -d "${BACKUP_ROOT}/weekly/latest" ]; then
    if verify_backup "${BACKUP_ROOT}/weekly/latest"; then
        log_info "✅ Weekly backup OK"
    else
        log_error "❌ Weekly backup verification failed"
        ((ERRORS++))
    fi
fi

# Check disk space
DISK_USAGE=$(df /root | tail -1 | awk '{print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -gt 80 ]; then
    log_warn "⚠️  Disk usage high: ${DISK_USAGE}%"
    ((ERRORS++))
fi

# Summary
if [ $ERRORS -eq 0 ]; then
    log_info "✅ All backup verifications passed"
    exit 0
else
    log_error "❌ Backup verification failed with $ERRORS errors"
    exit 1
fi
