#!/bin/bash
# Cron script to import Discogs data dumps monthly
# Add to crontab: 0 3 1 * * /path/to/export-folder-discogs/scripts/cron_import_dump.sh

cd "$(dirname "$0")/.."

# Activate virtual environment
source venv/bin/activate

# Run import with logging
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/import_dump_$(date +%Y%m%d_%H%M%S).log"

echo "==================================================================="
echo "  DISCOGS DUMP IMPORT - $(date)"
echo "==================================================================="

python scripts/import_discogs_dump.py 2>&1 | tee "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -eq 0 ]; then
    echo "✓ Import completed successfully"
else
    echo "❌ Import failed with code $EXIT_CODE"
fi

# Keep only last 10 logs
ls -t "$LOG_DIR"/import_dump_*.log | tail -n +11 | xargs -r rm

exit $EXIT_CODE
