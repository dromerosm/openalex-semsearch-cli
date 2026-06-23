# Web demo app

A full demo of the `oa` CLI's capabilities, meant to run on a small VPS (Hetzner):

- **Live semantic search** — real OpenAlex queries, hard-capped at 10 results,
  per-IP rate limited and TTL-cached. Renders a sortable impact table (citations,
  FWCI, field percentile with top-1%/10% markers).
- **Cluster explorer** — pre-generated datasets shown as an interactive 2D scatter
  (color = cluster, size ∝ citations) plus per-cluster cards with impact stats,
  dominant fields/keywords, a representative paper and a GPT description.

```
webapp/
  app.py                   FastAPI backend (search + examples API, serves static/)
  generate_examples.py     offline dataset generator (the only step that spends OpenAI)
  data/*.json              pre-generated cluster datasets (committed)
  static/                  index.html · styles.css · app.js (+ Plotly via CDN)
  Dockerfile               lean runtime image
  docker-compose.yml       deploy behind Traefik
  requirements.txt         local dev deps (on top of the editable package)
  requirements-server.txt  lean runtime deps (no numpy/sklearn/umap/openai)
```

## Cost model

| Surface | When | Cost |
|---|---|---|
| `search` (semantic/lexical) | live, per request | ~$0.001/query to OpenAlex (lexical free); capped at 10 + rate-limited |
| `cluster` explorer | **offline, once** | embeddings + GPT, run locally by `generate_examples.py` |

The production server therefore needs **only `OPENALEX_API_KEY`** — the OpenAI key
never leaves your machine.

## Run locally

```bash
# from repo root, with the package installed (uv pip install -e .)
.venv/bin/python -m pip install -r webapp/requirements.txt
.venv/bin/python -m uvicorn webapp.app:app --reload --port 8000
# open http://localhost:8000
```

Credentials come from `.env` / environment (`OPENALEX_API_KEY`, optional
`OPENALEX_MAILTO`), same as the CLI.

## Regenerate the cluster datasets (needs OpenAI key)

```bash
.venv/bin/python webapp/generate_examples.py                 # all topics, with GPT descriptions
.venv/bin/python webapp/generate_examples.py --only kelp-biomechanics
.venv/bin/python webapp/generate_examples.py --no-describe   # skip GPT
```

Edit the `TOPICS` list in `generate_examples.py` to change the example sets.

## Configuration (env vars)

| Var | Default | Meaning |
|---|---|---|
| `OPENALEX_API_KEY` | — | required for semantic search |
| `OPENALEX_MAILTO` | — | OpenAlex polite pool (recommended) |
| `OA_MAX_RESULTS` | `10` | hard cap on live search results |
| `OA_RATE_PER_MIN` | `20` | per-IP requests/minute |
| `OA_RATE_PER_DAY` | `200` | per-IP requests/day |
| `OA_CACHE_TTL` | `3600` | search cache TTL (seconds) |

## Deploy on Hetzner (Docker + Traefik + Cloudflare)

Assumes a Hetzner host already running Traefik on an external `traefik` network
(the layout the `cloudflare-hetzner-subdomain` skill sets up).

```bash
# 1. Point a Cloudflare subdomain (e.g. oa-demo.example.com) at the Hetzner host.
# 2. On the host, in this repo, create webapp/.env:
cat > webapp/.env <<'ENV'
OPENALEX_API_KEY=...
OPENALEX_MAILTO=you@example.com
OA_HOST=oa-demo.example.com
OA_CERTRESOLVER=le        # your Traefik cert resolver name
ENV
# 3. Build & start:
docker compose -f webapp/docker-compose.yml --env-file webapp/.env up -d --build
```

Traefik terminates HTTPS and routes the subdomain to the container's port 8000.
Rate limiting and the result cap protect the live OpenAlex calls; tighten
`OA_RATE_PER_*` for a public URL.
