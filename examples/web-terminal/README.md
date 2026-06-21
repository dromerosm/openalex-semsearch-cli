# Web terminal demo (`ttyd`)

Serve the `oa` CLI as an interactive **web terminal** so anyone can run live
queries from a browser — no local install. This is the "live" counterpart to the
recorded GIF in [`../demo/`](../demo/).

> Status: **not deployed.** These scripts are kept here for reference; run them
> locally when you want to show the CLI live. For a public demo, read the
> [Public deployment](#public-deployment) section first.

## Files

| File | What it does |
|---|---|
| `serve.sh` | Starts `ttyd` bound to `127.0.0.1`, serving `web-shell.sh`. |
| `web-shell.sh` | A **restricted REPL**: only `search`, `cluster`, `whoami`, `help` are accepted. Arguments are passed as `argv` (no `eval`), so shell injection like `whoami; rm -rf /` is rejected. |

## Requirements

- The project venv built at repo root (`.venv/`, see the main [README](../../README.md)).
- API keys available as env vars or in `.env` (`OPENALEX_API_KEY`, and
  `OPENAI_API_KEY` if you allow `cluster`).
- `ttyd`:

```bash
brew install ttyd        # macOS
# or: apt-get install ttyd
```

## Run locally

```bash
bash examples/web-terminal/serve.sh            # http://localhost:7681
PORT=8080 bash examples/web-terminal/serve.sh  # custom port
```

Open the URL and try:

```
search "llm agents for code" -n 5
search "crispr" --year 2024 --lexical -n 5
whoami
```

Stop it with `Ctrl-C`, or `pkill -f ttyd`.

## Cost note

`search` (semantic or `--lexical`) consumes **zero OpenAI embeddings**. Only
`cluster` spends OpenAI embeddings (and `--describe` adds GPT calls). For a
public, unattended demo, remove `cluster` from the `allowed` list in
`web-shell.sh` to avoid surprise spend.

## Public deployment

`serve.sh` binds to `127.0.0.1` only — it is **not** safe to expose as-is. To put
it online (e.g. Hetzner + Cloudflare):

1. Add basic auth: `ttyd --credential user:pass ...`.
2. Terminate **HTTPS** in front (Cloudflare → Traefik/Caddy/nginx); never serve a
   writable web terminal over plain HTTP.
3. Keep `cluster` disabled (see cost note) unless you trust the audience.
4. Run under a process manager (systemd / Docker) so it restarts cleanly.

A Hetzner VPS fits this better than Cloudflare Workers: the CLI is Python 3.14
with native scientific deps (`numpy`, `scikit-learn`, `umap-learn`) that do not
run in the Workers JS/WASM runtime.
