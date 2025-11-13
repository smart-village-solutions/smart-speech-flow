#!/bin/bash
# Common backup functions used by all backup scripts

set -e

# Configuration
PROJECT_ROOT="/root/projects/ssf-backend"
BACKUP_ROOT="${PROJECT_ROOT}/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Create backup directory
create_backup_dir() {
    local backup_type=$1
    local backup_dir="${BACKUP_ROOT}/${backup_type}/${TIMESTAMP}"
    mkdir -p "${backup_dir}"
    echo "${backup_dir}"
}

# Backup Grafana database and dashboards
backup_grafana() {
    log_info "Backing up Grafana..."
    local backup_dir=$1

    if [ -d "${PROJECT_ROOT}/monitoring/grafana" ]; then
        tar czf "${backup_dir}/grafana-db.tar.gz" \
            -C "${PROJECT_ROOT}/monitoring" grafana/
        log_info "Grafana database backed up"
    fi

    # Export dashboards via API
    if [ -f "${PROJECT_ROOT}/.env" ]; then
        PASSWORD=$(grep GRAFANA_ADMIN_PASSWORD "${PROJECT_ROOT}/.env" | cut -d'=' -f2)
        if [ -n "$PASSWORD" ] && curl -s http://localhost:3000/api/health > /dev/null 2>&1; then
            mkdir -p "${backup_dir}/grafana-dashboards"
            curl -s -u "admin:${PASSWORD}" http://localhost:3000/api/search?type=dash-db | \
                jq -r '.[] | .uid' 2>/dev/null | while read -r uid; do
                    if [ -n "$uid" ]; then
                        curl -s -u "admin:${PASSWORD}" \
                            "http://localhost:3000/api/dashboards/uid/${uid}" \
                            > "${backup_dir}/grafana-dashboards/${uid}.json"
                    fi
                done
            log_info "Grafana dashboards exported"
        fi
    fi
}

# Backup Prometheus data (recent)
backup_prometheus_recent() {
    log_info "Backing up Prometheus (last 24h)..."
    local backup_dir=$1

    if [ -d "${PROJECT_ROOT}/monitoring/prometheus" ]; then
        # Only backup recent data (last 24h)
        find "${PROJECT_ROOT}/monitoring/prometheus" -type f -mtime -1 -print0 | \
            tar czf "${backup_dir}/prometheus-recent.tar.gz" --null -T -
        log_info "Prometheus recent data backed up"
    fi
}

# Backup Prometheus data (full)
backup_prometheus_full() {
    log_info "Backing up Prometheus (full)..."
    local backup_dir=$1

    if [ -d "${PROJECT_ROOT}/monitoring/prometheus" ]; then
        tar czf "${backup_dir}/prometheus-full.tar.gz" \
            -C "${PROJECT_ROOT}/monitoring" prometheus/
        log_info "Prometheus full data backed up"
    fi
}

# Backup Loki logs (recent)
backup_loki_recent() {
    log_info "Backing up Loki (last 24h)..."
    local backup_dir=$1

    if [ -d "${PROJECT_ROOT}/monitoring/loki" ]; then
        find "${PROJECT_ROOT}/monitoring/loki" -type f -mtime -1 -print0 | \
            tar czf "${backup_dir}/loki-recent.tar.gz" --null -T -
        log_info "Loki recent logs backed up"
    fi
}

# Backup Loki logs (full)
backup_loki_full() {
    log_info "Backing up Loki (full)..."
    local backup_dir=$1

    if [ -d "${PROJECT_ROOT}/monitoring/loki" ]; then
        tar czf "${backup_dir}/loki-full.tar.gz" \
            -C "${PROJECT_ROOT}/monitoring" loki/
        log_info "Loki full logs backed up"
    fi
}

# Backup Redis data
backup_redis() {
    log_info "Backing up Redis..."
    local backup_dir=$1

    # Trigger Redis BGSAVE
    docker compose -f "${PROJECT_ROOT}/docker-compose.yml" exec -T redis \
        redis-cli BGSAVE > /dev/null 2>&1 || true

    sleep 2  # Wait for BGSAVE to complete

    # Copy dump.rdb if it exists
    docker compose -f "${PROJECT_ROOT}/docker-compose.yml" exec -T redis \
        cat /data/dump.rdb > "${backup_dir}/redis-dump.rdb" 2>/dev/null || \
        log_warn "Redis dump not available"
}

# Backup audio files
backup_audio_files() {
    log_info "Backing up audio files..."
    local backup_dir=$1

    if [ -d "${PROJECT_ROOT}/data/audio" ]; then
        tar czf "${backup_dir}/audio-files.tar.gz" \
            -C "${PROJECT_ROOT}/data" audio/
        log_info "Audio files backed up"
    fi
}

# Backup configuration files
backup_configs() {
    log_info "Backing up configuration files..."
    local backup_dir=$1

    mkdir -p "${backup_dir}/configs"

    # Backup important configs (excluding sensitive .env)
    cp "${PROJECT_ROOT}/docker-compose.yml" "${backup_dir}/configs/"
    cp "${PROJECT_ROOT}/.env.example" "${backup_dir}/configs/"
    cp -r "${PROJECT_ROOT}/monitoring/"*.yml "${backup_dir}/configs/" 2>/dev/null || true
    cp -r "${PROJECT_ROOT}/monitoring/"*.yaml "${backup_dir}/configs/" 2>/dev/null || true

    # Backup .env separately with encryption warning
    if [ -f "${PROJECT_ROOT}/.env" ]; then
        cp "${PROJECT_ROOT}/.env" "${backup_dir}/configs/.env.backup"
        echo "⚠️  Contains sensitive passwords - encrypt before remote backup" \
            > "${backup_dir}/configs/.env.backup.WARNING"
    fi

    log_info "Configuration files backed up"
}

# Backup Docker volumes
backup_docker_volumes() {
    log_info "Backing up Docker volumes..."
    local backup_dir=$1

    mkdir -p "${backup_dir}/volumes"

    # List all volumes for this project
    docker volume ls --filter "name=ssf-backend" --format "{{.Name}}" | while read -r volume; do
        log_info "Backing up volume: $volume"
        docker run --rm \
            -v "${volume}:/data" \
            -v "${backup_dir}/volumes:/backup" \
            alpine tar czf "/backup/${volume}.tar.gz" /data
    done

    log_info "Docker volumes backed up"
}

# Backup Git state
backup_git_state() {
    log_info "Backing up Git state..."
    local backup_dir=$1

    cd "${PROJECT_ROOT}"

    git rev-parse HEAD > "${backup_dir}/git-commit.txt"
    git branch --show-current > "${backup_dir}/git-branch.txt"
    git status --short > "${backup_dir}/git-status.txt"
    git diff > "${backup_dir}/git-diff.patch" 2>/dev/null || true

    log_info "Git state backed up"
}

# Backup Git archive (full repository)
backup_git_archive() {
    log_info "Backing up Git repository..."
    local backup_dir=$1

    cd "${PROJECT_ROOT}"
    git archive --format=tar.gz --prefix=ssf-backend/ HEAD \
        > "${backup_dir}/repository.tar.gz"

    log_info "Git repository archived"
}

# Backup documentation
backup_documentation() {
    log_info "Backing up documentation..."
    local backup_dir=$1

    if [ -d "${PROJECT_ROOT}/docs" ]; then
        tar czf "${backup_dir}/documentation.tar.gz" \
            -C "${PROJECT_ROOT}" docs/
        log_info "Documentation backed up"
    fi
}

# Complete system backup
backup_complete_system() {
    log_info "Creating complete system backup..."
    local backup_dir=$1

    backup_grafana "$backup_dir"
    backup_prometheus_full "$backup_dir"
    backup_loki_full "$backup_dir"
    backup_redis "$backup_dir"
    backup_audio_files "$backup_dir"
    backup_configs "$backup_dir"
    backup_docker_volumes "$backup_dir"
    backup_git_state "$backup_dir"

    log_info "Complete system backup finished"
}

# Cleanup old backups
cleanup_old_backups() {
    local backup_type=$1
    local retention_days=$2

    log_info "Cleaning up old $backup_type backups (retention: $retention_days days)..."

    find "${BACKUP_ROOT}/${backup_type}" -type d -mtime +${retention_days} -exec rm -rf {} \; 2>/dev/null || true

    log_info "Cleanup completed"
}

# Create backup summary
create_backup_summary() {
    local backup_dir=$1
    local backup_type=$2

    {
        echo "Backup Summary"
        echo "=============="
        echo "Type: $backup_type"
        echo "Date: $(date)"
        echo "Location: $backup_dir"
        echo ""
        echo "Contents:"
        du -sh "${backup_dir}"/* 2>/dev/null | sort -h
        echo ""
        echo "Total size: $(du -sh "${backup_dir}" | cut -f1)"
    } > "${backup_dir}/BACKUP_SUMMARY.txt"

    log_info "Backup summary created"
}

# Verify backup integrity
verify_backup() {
    local backup_dir=$1
    local errors=0

    log_info "Verifying backup integrity..."

    # Check all tar.gz files
    find "${backup_dir}" -name "*.tar.gz" -type f | while read -r archive; do
        if ! tar -tzf "$archive" > /dev/null 2>&1; then
            log_error "Corrupt archive: $archive"
            ((errors++))
        fi
    done

    # Check minimum backup size (should be at least 1MB)
    size=$(du -sm "${backup_dir}" | cut -f1)
    if [ "$size" -lt 1 ]; then
        log_error "Backup too small: ${size}MB"
        ((errors++))
    fi

    if [ $errors -eq 0 ]; then
        log_info "Backup verification passed ✓"
        return 0
    else
        log_error "Backup verification failed with $errors errors"
        return 1
    fi
}
