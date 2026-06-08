# Example: "agentic workflows" (2026)

End-to-end example with a date filter: **"agentic workflows" in 2026**.

> Data via OpenAlex (semantic search + impact). Run on 2026-06-08.
> Numbers change over time as OpenAlex updates citations/FWCI.

## 1. Semantic search with impact

```bash
oa search "agentic workflows" --year 2026 -n 15 \
  --export examples/agentic-workflows-2026/search.json
```

Top 6 (★ = top-1% of field/year · ▲ = top-10%). Full export in
[`search.json`](search.json):

| Title | Cites | FWCI | Norm. pctl | Field |
|---|---|---|---|---|
| From prompt injections to protocol exploits: … | 12 | 215 | 100% ★ | Decision Sciences |
| ChemGraph as an agentic framework for computa… | 6 | 31 | 100% ★ | Materials Science |
| The Agent-Centric Enterprise: Why 2–10x Produ… | 1 | 49 | 99% ▲ | Social Sciences |
| Benchmarking LLM-based agents for single-cell… | 2 | 15 | 98% ▲ | Biochemistry, Genetics… |
| SurgRAW: Multi-Agent Workflow With Chain of T… | 2 | 37 | 99% ★ | Computer Science |
| CDAFlow: Enhancing LLM clinical decision-maki… | 2 | 44 | 100% ★ | Decision Sciences |

## 2. Clustering by semantic similarity + impact

By default the number of clusters is **discovered with HDBSCAN** (no fixed `k`, with
prior reduction); papers that do not form a dense group are marked as *outliers*.
`--describe` generates a synthesis of each cluster with GPT from the abstracts.

```bash
oa cluster "agentic workflows" --year 2026 -n 30 --expand --describe \
  --export examples/agentic-workflows-2026/clusters.json
```

Summary (export with `cluster` and `cluster_description` per article in
[`clusters.json`](clusters.json)):

| Cluster | N | Total cites | Mean FWCI | Top10% | Dominant field |
|---|---|---|---|---|---|
| #0 | 2 | 13 | 126 | 2/2 | Decision Sciences |
| #1 | 4 | 10 | 14 | 4/4 | Materials Science |
| #2 | 2 | 7 | 26 | 2/2 | Biochemistry, Genetics… |
| #5 | 3 | 5 | 31 | 3/3 | Computer Science |
| #3 | 3 | 3 | 20 | 2/3 | Social Sciences |
| #4 | 2 | 2 | 34 | 2/2 | Health Professions |
| outliers | 2 | 2 | 7 | 2/2 | Chemistry |

Descriptions generated with `gpt-5.4-mini` (excerpt):

- **#0** — LLM-driven agentic workflows: their **security** (prompt injection, protocol
  exploits) and efficient execution via latency-aware **task offloading** on edge.
- **#1** — Agentic AI workflows that turn expert-heavy **scientific/engineering** tasks
  (chemistry, materials) into automated end-to-end pipelines.
- **#2** — Agentic AI to make **single-cell omics** (scRNA-seq) analysis automated,
  standardized and reproducible.
- **#5** — Multi-step agentic LLM workflows for **clinical/surgical** understanding,
  with chain-of-thought reasoning and specialized agents.
- **#3** — Autonomous agents embedded in **redesigned, repeatable workflows** for
  enterprise/web/IoT automation, not ad hoc assistants.
- **#4** — *Workflow-native* clinical AI integrated into real hospital systems
  (EHR/FHIR), moving from prediction to coordinated action.
- **outliers** — 2 genuinely isolated papers: one where "agents" are **chemical
  reagents**, and a lone **multi-agent RL** energy-trading paper.

> **Note on outliers.** HDBSCAN over the raw 1536-dim embeddings (`--reduce none`)
> marked **7/18** as outliers. On inspection several had cosine similarity 0.52–0.56
> with concrete clusters: not real outliers, but an artifact of the curse of
> dimensionality. Reducing dimensionality before HDBSCAN (here `--reduce auto` → PCA,
> since N<50) leaves **2 outliers**, both verified as genuine (similarity ≤0.51, no
> dense neighbor). On large datasets `auto` uses **UMAP** (better structure): e.g.
> CRISPR (N=120) went from 64 to 15 outliers.

## Fields retrieved per article

Each work is fetched **in bulk** (no per-article calls) with everything relevant.
The structured export (`.json`/`.csv`) includes:

- **Identity**: `id`, `doi`, `title`, `type`, `language`, `publication_date`, `year`.
- **Impact**: `cited_by_count`, `fwci`, `percentile_year`, `norm_percentile`,
  `is_top_10_percent`, `is_top_1_percent`, `referenced_works_count`,
  `counts_by_year` (citations-per-year series).
- **Topics / fields**: `topic` (+`topic_score`), `subfield`, `field`, `domain`,
  `keywords`, `sdgs` (Sustainable Development Goals).
- **Access / authorship**: `source`, `is_oa`, `oa_status`, `authors`, `institutions`,
  `countries`.
- **Text**: `abstract` (reconstructed; not full text). OpenAlex does not have an
  abstract for every work, so some are left empty (`has_abstract: false` upstream).

To dump the **complete OpenAlex object** (biblio, alternate ids, all locations, mesh,
grants, apc…):

```bash
oa search "agentic workflows" --year 2026 -n 15 --raw \
  --export examples/agentic-workflows-2026/raw.json
```

## Date filter

The date options act on `publication_year` (valid server-side in both semantic and
lexical search):

| Option | Generated filter |
|---|---|
| `--year 2026` | `publication_year:2026` |
| `--from-year 2024` | `publication_year:>2023` (>= 2024) |
| `--to-year 2025` | `publication_year:<2026` (<= 2025) |
| `--from-year 2024 --to-year 2026` | range 2024–2026 |

With `--expand`, `related_works` are fetched by ID (no server-side filter), so the year
filter — like the impact filter — is applied client-side to avoid leaking works from
other years.
