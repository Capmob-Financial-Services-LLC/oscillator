#!/bin/sh
# Lambda entrypoint for the Next.js server (standalone output). The Lambda Web
# Adapter layer starts this, then forwards each request to it on $PORT.
export HOSTNAME=0.0.0.0
exec node server.js
