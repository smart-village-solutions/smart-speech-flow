#!/bin/bash
# Install backup cron jobs

set -e

echo "Installing Smart Speech Flow backup cron jobs..."

# Create log directory
sudo mkdir -p /var/log/ssf-backups
sudo chown root:root /var/log/ssf-backups

# Add cron jobs
(crontab -l 2>/dev/null || true; cat << EOF

# Smart Speech Flow Backups
# Daily backup at 00:00 UTC (keeps 7 days)
0 0 * * * /root/projects/ssf-backend/scripts/backup-daily.sh >> /var/log/ssf-backups/daily.log 2>&1

# Weekly backup on Sunday at 01:00 UTC (keeps 4 weeks)
0 1 * * 0 /root/projects/ssf-backend/scripts/backup-weekly.sh >> /var/log/ssf-backups/weekly.log 2>&1

# Monthly backup on 1st day at 02:00 UTC (keeps 12 months)
0 2 1 * * /root/projects/ssf-backend/scripts/backup-monthly.sh >> /var/log/ssf-backups/monthly.log 2>&1

# Verify backups daily at 03:00 UTC
0 3 * * * /root/projects/ssf-backend/scripts/verify-backups.sh >> /var/log/ssf-backups/verify.log 2>&1
EOF
) | crontab -

echo "✅ Cron jobs installed successfully"
echo ""
echo "Installed jobs:"
crontab -l | grep "ssf-backend"
echo ""
echo "Logs will be written to /var/log/ssf-backups/"
