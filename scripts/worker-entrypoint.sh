#!/bin/sh
# Keep running after a failed cron attempt. Do not use set -e.

export API_READY_URL="${API_READY_URL:-http://api:8000/ready}"

echo "Starting daily digest worker (4am Europe/London start, 6am send)"
echo "Waiting for API to be ready at ${API_READY_URL}"

while true; do
  if PYTHONPATH=/app python -c "import os, urllib.request; urllib.request.urlopen(os.environ['API_READY_URL'], timeout=3)" >/dev/null 2>&1; then
    echo "API is ready"
    break
  fi
  echo "API not ready yet; retrying in 2s"
  sleep 2
done

while true; do
  echo "Waiting until today's 4am Europe/London (or starting now if already past)"
  PYTHONPATH=/app python -m core.cron_schedule wait-start || echo "Schedule wait-start failed"
  echo "Running daily digest cron"
  PYTHONPATH=/app python scripts/run_daily_cron.py || echo "Daily digest cron exited with an error"
  echo "Waiting until next 4am Europe/London"
  PYTHONPATH=/app python -m core.cron_schedule wait-next-start || echo "Schedule wait-next-start failed"
done
