#!/usr/bin/env bash
# Record the demo and render it to an animated GIF for the README.
# Requirements: asciinema, agg (brew install asciinema agg).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAST="$DIR/demo.cast"
GIF="$DIR/demo.gif"

asciinema rec "$CAST" \
  --overwrite \
  --headless \
  --window-size 110x30 \
  --idle-time-limit 2.5 \
  --title "openalex-cli (oa) demo" \
  --command "bash $DIR/demo.sh"

agg "$CAST" "$GIF" \
  --theme asciinema \
  --font-size 16 \
  --speed 1.4 \
  --idle-time-limit 2

echo "Wrote: $CAST and $GIF"
