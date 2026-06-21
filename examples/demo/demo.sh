#!/usr/bin/env bash
# Demo script for the `oa` CLI, intended to be captured with asciinema.
# Uses only `whoami` + `search` → zero OpenAI embeddings.
# Record with: examples/demo/record.sh
set -euo pipefail

# Resolve `oa` from the local venv without showing the path prefix in the demo.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PATH="$ROOT/.venv/bin:$PATH"

# asciinema's headless PTY sets TERM=dumb; force a real terminal so `clear`
# works and rich emits colors.
export TERM=xterm-256color
export COLUMNS=110

CYAN=$'\033[36m'; DIM=$'\033[2m'; RESET=$'\033[0m'
PROMPT="${CYAN}❯${RESET} "

# Type a command out like a human, then run it.
run() {
  local cmd="$1"
  printf '%s' "$PROMPT"
  for ((i = 0; i < ${#cmd}; i++)); do
    printf '%s' "${cmd:$i:1}"
    sleep 0.025
  done
  printf '\n'
  sleep 0.4
  eval "$cmd"
  sleep 2.2
}

note() { printf '\n%s# %s%s\n\n' "$DIM" "$1" "$RESET"; sleep 1.2; }

clear
note "openalex-cli (oa) — semantic search of papers with impact metrics"
run 'oa whoami'

clear
note "Semantic search: papers ranked with citations, FWCI and field percentile"
run 'oa search "graph neural networks for drug discovery" -n 4'

clear
note "Filter by year and sort by citations"
run 'oa search "kelp biomechanics" --from-year 2021 --sort cited_by_count:desc -n 4'

clear
note "Lexical (full-text) mode — no semantic embeddings at all"
run 'oa search "transformer architecture" --lexical -n 4'

clear
note "Also: oa cluster <query> — groups results by similarity and summarizes impact"
sleep 1.5
