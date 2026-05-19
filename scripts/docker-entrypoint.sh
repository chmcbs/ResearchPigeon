#!/bin/sh
set -e

python -m core.schema
exec uvicorn api:app --host 0.0.0.0 --port 8000
