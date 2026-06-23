"""Pre-generate cluster example datasets for the web demo (run offline).

This is the ONLY step that spends OpenAI embeddings (and, with --describe, GPT
calls). It runs locally with your keys and writes static JSON into webapp/data/,
which the production server serves without any live API cost.

    .venv/bin/python webapp/generate_examples.py            # all topics, with GPT descriptions
    .venv/bin/python webapp/generate_examples.py --no-describe
    .venv/bin/python webapp/generate_examples.py --only kelp-biomechanics

Each dataset JSON contains:
  - points[]   : one per work, with 2D coords (UMAP/PCA), cluster label and impact
  - clusters[] : per-cluster impact summary + representative work + GPT description
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openalex_cli.client import OpenAlexClient, Work
from openalex_cli.clustering import (
    _reduce,
    cluster_works,
    describe_clusters,
    embed_works,
)
from openalex_cli.config import load_settings

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"

# Curated mix: computer science / biology / climate-ocean.
TOPICS = [
    {"slug": "llm-for-code", "title": "LLMs for code", "query": "large language models for code generation"},
    {"slug": "crispr-off-target", "title": "CRISPR off-target effects", "query": "CRISPR off-target effects"},
    {"slug": "kelp-biomechanics", "title": "Kelp forest biomechanics", "query": "kelp forest biomechanics and wave drag"},
]

TARGET_WORKS = 70  # richer than the semantic 50-cap, via related-works expansion


def fetch_works(oa: OpenAlexClient, query: str, target: int) -> list[Work]:
    """Semantic search (cap 50) expanded via related_works up to `target`."""
    works = oa.search_works(query, semantic=True, limit=50, min_impact=True)
    have = {w.id for w in works}
    if len(works) < target:
        related: list[str] = []
        for w in works:
            for rid in w.related_works:
                if rid not in have:
                    related.append(rid)
        # Dedup preserving order.
        seen: set[str] = set()
        related = [r for r in related if not (r in seen or seen.add(r))]
        extra = oa.fetch_works_by_ids(related[: (target - len(works)) * 3])
        for w in extra:
            if w.id not in have and w.cited_by_count > 0 and w.fwci is not None:
                works.append(w)
                have.add(w.id)
                if len(works) >= target:
                    break
    return works[:target]


def build_dataset(topic: dict, works: list[Work], embeddings, clusters, n_clusters) -> dict:
    coords = _reduce(embeddings, "auto", 2)  # 2D for the scatter plot
    # Map each work id -> cluster label for the points.
    label_of: dict[str, int] = {}
    for c in clusters:
        for w in c.works:
            label_of[w.id] = c.label

    points = []
    for i, w in enumerate(works):
        points.append(
            {
                "id": w.id,
                "x": round(float(coords[i][0]), 4),
                "y": round(float(coords[i][1]), 4),
                "cluster": label_of.get(w.id, -1),
                "title": w.title,
                "year": w.year,
                "cited_by_count": w.cited_by_count,
                "fwci": w.fwci,
                "field": w.field,
                "is_top_10_percent": w.is_top_10_percent,
                "doi": w.doi,
            }
        )

    cluster_out = []
    for c in clusters:
        rep = c.representatives[0] if c.representatives else None
        cluster_out.append(
            {
                "label": c.label,
                "is_noise": c.is_noise,
                "size": c.size,
                "total_citations": c.total_citations,
                "mean_citations": round(c.mean_citations, 1),
                "mean_fwci": round(c.mean_fwci, 2) if c.mean_fwci is not None else None,
                "n_top_10_percent": c.n_top_10_percent,
                "top_fields": c.top_fields,
                "top_topics": c.top_topics,
                "top_domains": c.top_domains,
                "top_keywords": c.top_keywords,
                "representative": (
                    {"title": rep.title, "id": rep.id, "cited_by_count": rep.cited_by_count}
                    if rep
                    else None
                ),
                "description": c.description,
            }
        )

    return {
        "slug": topic["slug"],
        "title": topic["title"],
        "query": topic["query"],
        "mode": "semantic",
        "n_works": len(works),
        "n_clusters": n_clusters,
        "points": points,
        "clusters": cluster_out,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate cluster example datasets.")
    parser.add_argument("--no-describe", action="store_true", help="Skip GPT descriptions.")
    parser.add_argument("--only", help="Generate just one topic by slug.")
    parser.add_argument("--target", type=int, default=TARGET_WORKS, help="Works per dataset.")
    args = parser.parse_args()

    settings = load_settings()
    if not settings.openalex_api_key:
        raise SystemExit("OPENALEX_API_KEY is required.")
    if not args.no_describe and not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY required for descriptions (or pass --no-describe).")
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY is required for embeddings.")

    DATA_DIR.mkdir(exist_ok=True)
    topics = [t for t in TOPICS if not args.only or t["slug"] == args.only]
    if not topics:
        raise SystemExit(f"No topic matches --only {args.only!r}.")

    index = []
    with OpenAlexClient(api_key=settings.openalex_api_key, mailto=settings.mailto) as oa:
        for topic in topics:
            print(f"[{topic['slug']}] searching '{topic['query']}'...")
            works = fetch_works(oa, topic["query"], args.target)
            print(f"  fetched {len(works)} works; embedding...")
            embeddings = embed_works(works, settings.openai_api_key, settings.openai_embed_model)
            print("  clustering...")
            clusters, n_clusters = cluster_works(works, embeddings, k=None)
            print(f"  {n_clusters} clusters (+{sum(c.is_noise for c in clusters)} noise group)")
            if not args.no_describe:
                print("  describing clusters with GPT...")
                try:
                    describe_clusters(clusters, settings.openai_api_key, settings.openai_describe_model)
                except Exception as e:  # noqa: BLE001 — don't lose the dataset over a describe failure
                    print(f"  WARNING: describe failed ({e}); leaving descriptions empty.")

            dataset = build_dataset(topic, works, embeddings, clusters, n_clusters)
            out = DATA_DIR / f"{topic['slug']}.json"
            out.write_text(json.dumps(dataset, ensure_ascii=False, indent=2))
            print(f"  wrote {out.relative_to(HERE.parent)}")
            index.append(
                {
                    "slug": topic["slug"],
                    "title": topic["title"],
                    "query": topic["query"],
                    "n_works": dataset["n_works"],
                    "n_clusters": dataset["n_clusters"],
                }
            )

    (DATA_DIR / "index.json").write_text(json.dumps({"examples": index}, ensure_ascii=False, indent=2))
    print(f"wrote {(DATA_DIR / 'index.json').relative_to(HERE.parent)} ({len(index)} examples)")


if __name__ == "__main__":
    main()
