# openalex-cli (`oa`)

[![CI](https://github.com/dromerosm/openalex-semsearch-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/dromerosm/openalex-semsearch-cli/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue.svg)](https://www.python.org/)

A research-oriented CLI for [OpenAlex](https://openalex.org): **semantic search** of
papers, retrieval of their **impact** (citations, FWCI, percentile), and **cluster
analysis** by semantic similarity.

> API rules and compliance: see [docs/references.md](docs/references.md)
> (based on the official [LLM Quick Reference](https://developers.openalex.org/guides/llm-quick-reference)).

## Why not the official CLI?

OpenAlex publishes an official CLI ([`openalex-official`](https://pypi.org/project/openalex-official/)),
but it is designed for **bulk download** of metadata/PDF/TEI-XML by filters or DOIs. It
does not do semantic search or clustering. This CLI fills that gap by leveraging:

- OpenAlex's `search.semantic` parameter (GTE-Large embeddings, beta, ~$0.001/query);
- OpenAI embeddings + clustering to group the results and summarize their impact.

## Requirements

- Python >= 3.14
- A `.env` at the project root with:

```dotenv
OPENALEX_API_KEY=...        # required for semantic search
OPENAI_API_KEY=...          # required for the `cluster` command
# optional:
OPENALEX_MAILTO=you@email   # enters OpenAlex's "polite pool"
OPENAI_EMBED_MODEL=text-embedding-3-small
OPENAI_DESCRIBE_MODEL=gpt-5.4-mini   # model for `cluster --describe`
```

## Installation

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -e .
```

## Usage

```bash
# Check detected credentials
.venv/bin/oa whoami

# Semantic search with impact
.venv/bin/oa search "graph neural networks for drug discovery" -n 25

# Filter and sort; export to CSV/JSON
.venv/bin/oa search "kelp biomechanics" -n 50 \
  --filter "publication_year:>2020,is_oa:true" \
  --sort cited_by_count:desc \
  --export results.csv

# Date filter (shortcuts over publication_year)
.venv/bin/oa search "agentic workflows" --year 2026
.venv/bin/oa search "diffusion models" --from-year 2023 --to-year 2025

# Lexical (full-text) search instead of semantic
.venv/bin/oa search "transformer architecture" --lexical

# Cluster: by default the number of clusters is discovered with HDBSCAN
.venv/bin/oa cluster "large language models for code" -n 80
# Force the number of clusters with KMeans
.venv/bin/oa cluster "CRISPR off-target effects" -n 100 --k 5 --export clusters.json

# Describe each cluster with GPT from the abstracts
.venv/bin/oa cluster "agentic workflows" --year 2026 -n 30 --expand --describe

# Expand beyond the semantic 50-result cap, in bulk (1 call / 100 works)
.venv/bin/oa cluster "agentic workflows" --year 2026 -n 30 --expand
```

(Activate the venv with `source .venv/bin/activate` and you can drop the `.venv/bin/` prefix.)

A full worked example is in [examples/](examples/README.md).

## Commands

| Command | What it does |
|---|---|
| `oa search <query>` | Retrieve papers (semantic by default) with citations, FWCI and percentile. |
| `oa cluster <query>` | Retrieve, embed (OpenAI), cluster, and summarize impact per cluster. |
| `oa whoami` | Show which credentials are detected in `.env`. |

### Data retrieved per paper

Each work is fetched **in bulk** (no per-paper calls) with everything relevant.
`select` adds no calls, so the full set is requested:

- **Impact**: `cited_by_count`, `fwci` (*Field-Weighted Citation Impact*; 1.0 = field
  average), `cited_by_percentile_year`, `citation_normalized_percentile` (+ **top-1% /
  top-10%** flags), `referenced_works_count`, and `counts_by_year` (citations-per-year
  series).
- **Topics / fields** (hierarchy `domain > field > subfield > topic`): `primary_topic`
  with `topic_score`, plus `field`, `subfield`, `domain`, `keywords` and
  `sustainable_development_goals`.
- **Metadata**: `type`, `language`, `publication_date`, `source`, `is_oa`/`oa_status`,
  authors, institutions and countries.
- **Text**: `abstract` (reconstructed from the inverted index; **not** full text). Some
  works have no abstract in OpenAlex and are left empty.

In the tables, ★ marks top-1% and ▲ top-10% (percentile normalized by field and year).
`oa search ... --raw --export f.json` dumps the **complete OpenAlex object** (biblio,
alternate ids, all locations, mesh, grants, apc…) with no extra calls.

### Impact filter (`--min-impact`)

By default `search` and `cluster` only return papers with **>=1 citation and a FWCI
value** (`cited_by_count:>0,fwci:>0`). Turn it off with `--no-min-impact`.

- In **lexical** search it is applied as a server-side filter (discarded works are not
  fetched).
- In **semantic** search the API does not support those filters, so candidates are
  fetched (max 50) and filtered client-side. Same for `--expand` works (fetched by ID
  and filtered after the bulk fetch).

### Clustering: discovery vs. fixed k

- **Without `--k`** → **HDBSCAN**: discovers the number of clusters by density and
  marks as *outliers* the papers that do not form a group (it does not force them into
  a cluster). Tune granularity with `--min-cluster-size` (default 2; raise for larger
  groups).
- **With `--k N`** → **KMeans** with that k (explicit override).

**Dimensionality reduction (`--reduce`).** HDBSCAN over 1536-dim embeddings over-flags
outliers (density is unreliable in high dimensions: in one test it went from 60% to 16%
false outliers after reducing). So dimensionality is reduced before clustering:

- `auto` (default) — **PCA** if N<50 (stable on small datasets), **UMAP** if N>=50.
- `umap` — preserves local structure better (BERTopic standard); needs enough points.
- `pca` — linear and stable, low compute cost.
- `none` — on the full embeddings (not recommended).

Clusters are sorted by **total citations** and show their **dominant field/domain and
topics**, how many works are in the top-10% of their field, and the most representative
paper (closest to the centroid).

### Describe clusters with GPT (`--describe`)

`oa cluster ... --describe` generates, for each cluster, a synthesis in English from
the **abstracts** of its papers (one call per cluster). The model is
`OPENAI_DESCRIBE_MODEL` (default `gpt-5.4-mini`), or `--describe-model <id>`. The
descriptions are printed below the table and added to the export as
`cluster_description`.

### Minimizing API calls (bulk)

The CLI avoids N+1 patterns:

- **Semantic search** returns the complete works (with impact) in **1 call** (max 50
  results; lexical fetches up to 100/call via cursor).
- OpenAI **embeddings** are requested **in batches**.
- `--expand` uses `related_works` (already in the response) and fetches them with the
  OR-filter `ids.openalex:W1|W2|...` → **1 call per 100 works** instead of one per work.
  Reusable as `OpenAlexClient.fetch_works_by_ids(ids)`.

## Citing OpenAlex

This CLI uses OpenAlex data. If you publish results obtained with it, please cite:

> Priem, J., Piwowar, H., & Orr, R. (2022). *OpenAlex: A fully-open index of scholarly
> works, authors, venues, institutions, and concepts.* ArXiv.
> <https://arxiv.org/abs/2205.01833>

```bibtex
@article{priem2022openalex,
  title   = {OpenAlex: A fully-open index of scholarly works, authors, venues, institutions, and concepts},
  author  = {Priem, Jason and Piwowar, Heather and Orr, Richard},
  journal = {arXiv preprint arXiv:2205.01833},
  year    = {2022},
  url     = {https://arxiv.org/abs/2205.01833}
}
```
