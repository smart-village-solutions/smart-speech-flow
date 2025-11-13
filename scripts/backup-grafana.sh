#!/bin/bash
# Grafana Backup Script
# Creates timestamped backups of Grafana database and dashboards

set -e

BACKUP_DIR="./backups/grafana"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="${BACKUP_DIR}/${TIMESTAMP}"

echo "Creating Grafana backup at ${BACKUP_PATH}..."

# Create backup directory
mkdir -p "${BACKUP_PATH}"

# Backup Grafana database
if [ -d "./monitoring/grafana" ]; then
    echo "Backing up Grafana database..."
    cp -r ./monitoring/grafana "${BACKUP_PATH}/database"
fi

# Export dashboards via API
if command -v curl &> /dev/null; then
    echo "Exporting dashboards via API..."
    PASSWORD=$(grep GRAFANA_ADMIN_PASSWORD .env | cut -d'=' -f2)
    if [ -n "$PASSWORD" ]; then
        mkdir -p "${BACKUP_PATH}/dashboards"
        curl -s -u "admin:${PASSWORD}" http://localhost:3000/api/search?type=dash-db | \
            jq -r '.[] | .uid' | while read -r uid; do
                curl -s -u "admin:${PASSWORD}" "http://localhost:3000/api/dashboards/uid/${uid}" > \
                    "${BACKUP_PATH}/dashboards/${uid}.json"
                echo "Exported dashboard: ${uid}"
            done
    fi
fi

echo "✅ Backup complete: ${BACKUP_PATH}"
echo "To restore: cp -r ${BACKUP_PATH}/database/* ./monitoring/grafana/"
