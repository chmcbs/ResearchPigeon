#!/bin/sh
# Keep running after a failed cron attempt. Do not use set -e.

echo "Starting daily digest worker (4am Europe/London start, 6am send)"

while true; do
  echo "Waiting until today's 4am Europe/London (or starting now if already past)"
  PYTHONPATH=/app python -m core.cron_schedule wait-start || echo "Schedule wait-start failed"
  echo "Running daily digest cron"
  PYTHONPATH=/app python scripts/run_daily_cron.py || echo "Daily digest cron exited with an error"
  echo "Waiting until next 4am Europe/London"
  PYTHONPATH=/app python -m core.cron_schedule wait-next-start || echo "Schedule wait-next-start failed"
done
