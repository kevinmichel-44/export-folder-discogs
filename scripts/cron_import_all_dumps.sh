#!/bin/bash
# Cron script to import all Discogs dumps monthly
# Add to crontab: 0 3 1 * * /path/to/export-folder-discogs/scripts/cron_import_all_dumps.sh

cd "$(dirname "$0")/.."

# Activate virtual environment
source venv/bin/activate

# Run import with logging
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/import_all_dumps_$(date +%Y%m%d_%H%M%S).log"

echo "==================================================================="
echo "  DISCOGS ALL DUMPS IMPORT - $(date)"
echo "==================================================================="

python scripts/import_all_dumps.py --types artists labels masters releases 2>&1 | tee "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -eq 0 ]; then
    echo "✓ Import completed successfully"
else
    echo "❌ Import failed with code $EXIT_CODE"
fi

# Keep only last 10 logs
cd "$LOG_DIR" || exit 1
ls -t import_all_dumps_*.log 2>/dev/null | tail -n +11 | xargs -r rm

exit $EXIT_CODE
