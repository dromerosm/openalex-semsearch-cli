#!/usr/bin/env bash
# Restricted REPL exposed by the web terminal: only the `oa` subcommands are
# allowed (no arbitrary shell). Intended to be served by ttyd (see serve.sh).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PATH="$ROOT/.venv/bin:$PATH"
export TERM=xterm-256color

CYAN=$'\033[36m'; DIM=$'\033[2m'; BOLD=$'\033[1m'; RESET=$'\033[0m'

printf '%sopenalex-cli — web demo%s\n' "$BOLD" "$RESET"
printf '%sTry:%s search "llm agents for code" -n 5   ·   search "crispr" --year 2024 --lexical -n 5   ·   whoami\n' "$DIM" "$RESET"
printf '%sOnly the `oa` subcommands below are allowed. Type `quit` to exit.%s\n' "$DIM" "$RESET"

allowed='search cluster whoami help'

while true; do
  if ! read -e -r -p $'\n'"${CYAN}oa ❯${RESET} " line; then
    break
  fi
  line="${line#"${line%%[![:space:]]*}"}"   # ltrim
  [ -z "$line" ] && continue
  cmd="${line%%[[:space:]]*}"               # first token
  case "$cmd" in
    quit|exit) break ;;
    help|--help|-h) oa --help; continue ;;
  esac
  if [[ " $allowed " != *" $cmd "* ]]; then
    printf '%sNot allowed:%s %q — use one of: %s\n' "$DIM" "$RESET" "$cmd" "$allowed"
    continue
  fi
  # Split on whitespace only (no shell metachars): tokens go straight to argv.
  read -r -a args <<< "$line"
  oa "${args[@]}"
done
