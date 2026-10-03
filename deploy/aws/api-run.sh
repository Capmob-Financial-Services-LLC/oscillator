#!/bin/sh
# Lambda entrypoint for the FastAPI backend. The Lambda Web Adapter layer
# starts this, waits for /health, then forwards each request to it on $PORT.
export PYTHONPATH="$LAMBDA_TASK_ROOT"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --no-access-log
