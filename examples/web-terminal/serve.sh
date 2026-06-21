#!/usr/bin/env bash
# Serve the `oa` CLI as a web terminal with ttyd (option 2: live demo).
# Requirements: ttyd (brew install ttyd).
#
#   bash examples/web-terminal/serve.sh            # http://localhost:7681 (read/write)
#   PORT=8080 bash examples/web-terminal/serve.sh  # custom port
#
# For a public demo, put it behind HTTPS + auth (Cloudflare + Hetzner) and
# pass --credential user:pass. Locally this binds to 127.0.0.1 only.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-7681}"

exec ttyd \
  --port "$PORT" \
  --interface 127.0.0.1 \
  --writable \
  -t titleFixed="openalex-cli demo" \
  bash "$DIR/web-shell.sh"
