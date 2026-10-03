#!/bin/sh
# Lambda entrypoint for the FastAPI backend. The Lambda Web Adapter layer
# starts this, waits for /health, then forwards each request to it on $PORT.
#
# DATABASE_URL is read from SSM (SecureString) at cold start rather than set
# on the function, so the Neon password is never in the Lambda configuration
# or in Terraform state, and rotating it needs no deploy: the next cold start
# picks it up. boto3 ships with the Lambda Python runtime.
set -e
export PYTHONPATH="$LAMBDA_TASK_ROOT"
if [ -z "$DATABASE_URL" ] && [ -n "$DATABASE_URL_PARAM" ]; then
  DATABASE_URL="$(python -c 'import os, boto3; print(boto3.client("ssm").get_parameter(Name=os.environ["DATABASE_URL_PARAM"], WithDecryption=True)["Parameter"]["Value"])')"
  export DATABASE_URL
fi
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --no-access-log
