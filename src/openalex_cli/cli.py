"""`oa` command-line interface."""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .citations import BUCKETS, build_profile, cites_per_month, parse_date, series_str
from .client import MAX_IDS_PER_FILTER, OpenAlexClient, OpenAlexError, Work
from .config import load_settings

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="OpenAlex CLI: semantic search of papers and impact-based cluster analysis.",
)
console = Console()
err = Console(stderr=True)

def _build_filter(
    user_filter: Optional[str],
    year: Optional[int],
    from_year: Optional[int],
    to_year: Optional[int],
) -> Optional[str]:
    """Combine the user's --filter with a date filter on publication_year.

    `publication_year` is valid server-side in both semantic and lexical search
    (unlike from/to_publication_date, which semantic search rejects).
    """
    clauses: list[str] = []
    if user_filter:
        clauses.append(user_filter.strip())
    if year is not None:
        clauses.append(f"publication_year:{year}")
    else:
        if from_year is not None:
            clauses.append(f"publication_year:>{from_year - 1}")  # >= from_year
        if to_year is not None:
            clauses.append(f"publication_year:<{to_year + 1}")  # <= to_year
    return ",".join(c for c in clauses if c) or None


def _year_ok(
    work: Work, year: Optional[int], from_year: Optional[int], to_year: Optional[int]
) -> bool:
    """Check the year client-side (for works fetched by ID, without a server filter)."""
    if year is not None:
        return work.year == year
    if from_year is not None and (work.year is None or work.year < from_year):
        return False
    if to_year is not None and (work.year is None or work.year > to_year):
        return False
    return True


def _short_id(work_id: str) -> str:
    return work_id.rsplit("/", 1)[-1] if work_id else ""


def _fmt(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _counts_by_year_str(counts: list[dict]) -> str:
    """Citations-per-year series, compact for CSV: '2026:2;2025:5'."""
    return ";".join(
        f"{c.get('year')}:{c.get('cited_by_count')}" for c in counts if c.get("year")
    )


def _works_to_rows(works: list[Work]) -> list[dict]:
    return [
        {
            "id": _short_id(w.id),
            "title": w.title,
            "year": w.year,
            "publication_date": w.publication_date,
            "type": w.type,
            "language": w.language,
            # impact
            "cited_by_count": w.cited_by_count,
            "fwci": w.fwci,
            "percentile_year": w.percentile,
            "norm_percentile": w.norm_percentile,
            "is_top_10_percent": w.is_top_10_percent,
            "is_top_1_percent": w.is_top_1_percent,
            "referenced_works_count": w.referenced_works_count,
            "counts_by_year": _counts_by_year_str(w.counts_by_year),
            "relevance": w.relevance,
            # topics / fields
            "topic": w.topic,
            "topic_score": w.topic_score,
            "subfield": w.subfield,
            "field": w.field,
            "domain": w.domain,
            "keywords": "; ".join(w.keywords),
            "sdgs": "; ".join(w.sdgs),
            # access / authorship
            "source": w.source,
            "is_oa": w.is_oa,
            "oa_status": w.oa_status,
            "authors": "; ".join(w.authors[:8]),
            "institutions": "; ".join(dict.fromkeys(w.institutions)),
            "countries": "; ".join(dict.fromkeys(w.countries)),
            "doi": w.doi,
            # reconstructed abstract (not full text); already in the bulk response.
            "abstract": w.abstract,
        }
        for w in works
    ]


def _export(rows: list[dict], path: Path) -> None:
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    elif path.suffix.lower() == ".csv":
        if not rows:
            path.write_text("", encoding="utf-8")
        else:
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
    else:
        raise typer.BadParameter("Export path must end in .json or .csv")


def _pct(value: float | None) -> str:
    """Normalized percentile 0-1 as a percentage."""
    return "—" if value is None else f"{value * 100:.0f}%"


def _print_works_table(works: list[Work], title: str) -> None:
    table = Table(title=title, show_lines=False, header_style="bold cyan")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Title", overflow="fold", max_width=52)
    table.add_column("Year", justify="right")
    table.add_column("Cites", justify="right", style="green")
    table.add_column("FWCI", justify="right")
    table.add_column("Pctl", justify="right", header_style="bold cyan")  # norm percentile
    table.add_column("Field", overflow="fold", max_width=22)
    table.add_column("Topic", overflow="fold", max_width=24)
    for i, w in enumerate(works, 1):
        # High-impact marker: ★ top-1%, ▲ top-10%.
        mark = " ★" if w.is_top_1_percent else (" ▲" if w.is_top_10_percent else "")
        table.add_row(
            str(i),
            w.title,
            _fmt(w.year),
            _fmt(w.cited_by_count),
            _fmt(w.fwci),
            _pct(w.norm_percentile) + mark,
            _fmt(w.field),
            _fmt(w.topic),
        )
    console.print(table)


def _make_client() -> OpenAlexClient:
    settings = load_settings()
    return OpenAlexClient(api_key=settings.openalex_api_key, mailto=settings.mailto)


@app.command()
def search(
    query: str = typer.Argument(..., help="Search text (natural language)."),
    limit: int = typer.Option(25, "--limit", "-n", help="Number of papers to retrieve."),
    lexical: bool = typer.Option(
        False, "--lexical", help="Use lexical full-text search instead of semantic search."
    ),
    filters: Optional[str] = typer.Option(
        None, "--filter", help="OpenAlex filter, e.g. 'publication_year:>2020,is_oa:true'."
    ),
    year: Optional[int] = typer.Option(None, "--year", help="Exact publication year."),
    from_year: Optional[int] = typer.Option(
        None, "--from-year", help="From this year (inclusive). Ignored if --year is set."
    ),
    to_year: Optional[int] = typer.Option(
        None, "--to-year", help="Up to this year (inclusive). Ignored if --year is set."
    ),
    min_impact: bool = typer.Option(
        True,
        "--min-impact/--no-min-impact",
        help="Only papers with >=1 citation and a FWCI value (on by default).",
    ),
    sort: Optional[str] = typer.Option(
        None, "--sort", help="Sort, e.g. 'cited_by_count:desc'."
    ),
    export: Optional[Path] = typer.Option(
        None, "--export", help="Save results to .json or .csv."
    ),
    raw: bool = typer.Option(
        False,
        "--raw",
        help="With --export .json, dump the full OpenAlex object (all fields).",
    ),
) -> None:
    """Search papers in OpenAlex and show their impact (citations, FWCI, percentile)."""
    semantic = not lexical
    effective_filter = _build_filter(filters, year, from_year, to_year)
    try:
        with _make_client() as client:
            works = client.search_works(
                query,
                semantic=semantic,
                limit=limit,
                filters=effective_filter,
                sort=sort,
                min_impact=min_impact,
                full=raw,
            )
    except OpenAlexError as e:
        err.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    if not works:
        err.print("[yellow]No results.[/yellow]")
        raise typer.Exit(0)

    mode = "semantic" if semantic else "lexical"
    _print_works_table(works, f"OpenAlex — {mode} search: '{query}' ({len(works)} works)")

    if export:
        if raw:
            if export.suffix.lower() != ".json":
                raise typer.BadParameter("--raw requires a .json export")
            export.write_text(
                json.dumps([w.raw for w in works], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            _export(_works_to_rows(works), export)
        console.print(f"[green]Exported:[/green] {export}")


@app.command()
def cluster(
    query: str = typer.Argument(..., help="Semantic search text."),
    limit: int = typer.Option(80, "--limit", "-n", help="Papers to retrieve before clustering."),
    k: Optional[int] = typer.Option(
        None,
        "--k",
        help="Force the number of clusters (KMeans). If omitted, discovered via HDBSCAN.",
    ),
    min_cluster_size: int = typer.Option(
        2,
        "--min-cluster-size",
        help="HDBSCAN: minimum cluster size. Raise it for larger groups.",
    ),
    reduce: str = typer.Option(
        "auto",
        "--reduce",
        help="Reduction before HDBSCAN: auto (default: pca if N<50, else umap), umap, pca or none.",
    ),
    describe: bool = typer.Option(
        False,
        "--describe",
        help="Describe each cluster with GPT from the abstracts (uses OpenAI).",
    ),
    describe_model: Optional[str] = typer.Option(
        None,
        "--describe-model",
        help="Model for --describe (default: OPENAI_DESCRIBE_MODEL or gpt-5.4-mini).",
    ),
    lexical: bool = typer.Option(
        False, "--lexical", help="Retrieve with full-text instead of semantic search."
    ),
    filters: Optional[str] = typer.Option(
        None, "--filter", help="OpenAlex filter applied to retrieval."
    ),
    year: Optional[int] = typer.Option(None, "--year", help="Exact publication year."),
    from_year: Optional[int] = typer.Option(
        None, "--from-year", help="From this year (inclusive). Ignored if --year is set."
    ),
    to_year: Optional[int] = typer.Option(
        None, "--to-year", help="Up to this year (inclusive). Ignored if --year is set."
    ),
    min_impact: bool = typer.Option(
        True,
        "--min-impact/--no-min-impact",
        help="Only papers with >=1 citation and a FWCI value (on by default).",
    ),
    expand: bool = typer.Option(
        False,
        "--expand",
        help="Expand the set with each seed's related_works (fetched in bulk) "
        "to go beyond the semantic 50-result cap while minimizing calls.",
    ),
    export: Optional[Path] = typer.Option(
        None, "--export", help="Save works with their cluster to .json or .csv."
    ),
) -> None:
    """Retrieve papers, group them by semantic similarity, and summarize impact per cluster."""
    # Deferred import: sklearn/openai are heavy and only needed for clustering.
    from .clustering import cluster_works, describe_clusters, embed_works

    if reduce not in {"auto", "umap", "pca", "none"}:
        raise typer.BadParameter("--reduce must be auto, umap, pca or none")

    settings = load_settings()
    if not settings.has_openai:
        err.print("[red]Error:[/red] OPENAI_API_KEY missing in .env (required for embeddings).")
        raise typer.Exit(1)

    effective_filter = _build_filter(filters, year, from_year, to_year)
    try:
        with _make_client() as client:
            works = client.search_works(
                query,
                semantic=not lexical,
                limit=limit,
                filters=effective_filter,
                min_impact=min_impact,
            )
            if expand and works:
                seed_ids = {w.id for w in works}
                related = [
                    rid for w in works for rid in w.related_works if rid not in seed_ids
                ]
                if related:
                    # Bulk: 1 call per MAX_IDS_PER_FILTER IDs (not one per work).
                    n_unique = len(set(related))
                    n_calls = -(-n_unique // MAX_IDS_PER_FILTER)  # ceil
                    extra = client.fetch_works_by_ids(related)
                    # Fetch-by-ID applies no server-side filters: replicate the
                    # impact and year filters client-side.
                    extra = [w for w in extra if _year_ok(w, year, from_year, to_year)]
                    if min_impact:
                        extra = [
                            w for w in extra if w.cited_by_count > 0 and w.fwci is not None
                        ]
                    works.extend(extra)
                    console.print(
                        f"[dim]Expansion: +{len(extra)} works via related_works "
                        f"({n_calls} bulk call(s)).[/dim]"
                    )
    except OpenAlexError as e:
        err.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    if len(works) < 2:
        err.print(f"[yellow]Only {len(works)} result(s); need >=2 to cluster.[/yellow]")
        raise typer.Exit(1)

    method = "KMeans (fixed k)" if k else f"HDBSCAN (discovery, reduce={reduce})"
    with console.status(f"Generating embeddings and clustering with {method}…"):
        embeddings = embed_works(
            works, settings.openai_api_key, settings.openai_embed_model
        )
        clusters, resolved_k = cluster_works(
            works, embeddings, k=k, min_cluster_size=min_cluster_size, reduce=reduce
        )

    model_used = describe_model or settings.openai_describe_model
    if describe:
        try:
            with console.status(f"Describing {resolved_k} clusters with {model_used}…"):
                describe_clusters(clusters, settings.openai_api_key, model_used)
        except Exception as e:  # noqa: BLE001 - surface the model error without aborting
            err.print(f"[yellow]Could not generate descriptions ({e}).[/yellow]")

    n_noise = sum(c.size for c in clusters if c.is_noise)
    noise_note = f" · {n_noise} outliers" if n_noise else ""
    console.print(
        f"\n[bold]{len(works)}[/bold] papers → [bold]{resolved_k}[/bold] clusters "
        f"via {method}{noise_note}\n"
    )

    def _label(c) -> str:
        return "outliers" if c.is_noise else f"#{c.label}"

    summary = Table(title=f"Clusters for '{query}'", header_style="bold cyan", show_lines=True)
    summary.add_column("Cluster", justify="right")
    summary.add_column("N", justify="right")
    summary.add_column("Total cites", justify="right", style="green")
    summary.add_column("Mean FWCI", justify="right")
    summary.add_column("Top10%", justify="right")
    summary.add_column("Dominant field / domain", overflow="fold", max_width=26)
    summary.add_column("Dominant topics", overflow="fold", max_width=30)
    summary.add_column("Representative paper", overflow="fold", max_width=34)

    for c in clusters:
        topics = ", ".join(f"{t} ({n})" for t, n in c.top_topics) or "—"
        field = c.top_fields[0][0] if c.top_fields else "—"
        domain = c.top_domains[0][0] if c.top_domains else "—"
        rep = c.representatives[0].title if c.representatives else "—"
        summary.add_row(
            _label(c),
            str(c.size),
            str(c.total_citations),
            _fmt(c.mean_fwci),
            f"{c.n_top_10_percent}/{c.size}",
            f"{field}\n[dim]{domain}[/dim]",
            topics,
            rep,
        )
    console.print(summary)

    if describe and any(c.description for c in clusters):
        console.print("\n[bold cyan]Descriptions[/bold cyan] " f"[dim]({model_used})[/dim]")
        for c in clusters:
            if c.description:
                console.print(f"\n[bold]{_label(c)}[/bold] · {c.description}")

    if export:
        cluster_by_id = {id(w): c for c in clusters for w in c.works}
        rows = _works_to_rows(works)
        for row, w in zip(rows, works):
            c = cluster_by_id.get(id(w))
            row["cluster"] = c.label if c else None
            row["cluster_description"] = c.description if c else None
        _export(rows, export)
        console.print(f"\n[green]Exported:[/green] {export}")


def _ids_from_export(path: Path) -> list[str]:
    """Read work IDs from a previous `--export` file (.json or .csv, column `id`)."""
    if not path.exists():
        raise typer.BadParameter(f"File not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".json":
        rows = json.loads(path.read_text(encoding="utf-8"))
    elif suffix == ".csv":
        with path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    else:
        raise typer.BadParameter("--from-export must be a .json or .csv file")
    return [_short_id(str(r["id"])) for r in rows if isinstance(r, dict) and r.get("id")]


@app.command()
def citations(
    ids: Optional[list[str]] = typer.Argument(
        None, help="OpenAlex work IDs (W123… or full URL)."
    ),
    from_export: Optional[Path] = typer.Option(
        None,
        "--from-export",
        help="Take the work IDs from a previous search/cluster --export file.",
    ),
    bucket: str = typer.Option(
        "month", "--bucket", help="Series granularity: day, week or month."
    ),
    since: Optional[str] = typer.Option(
        None, "--since", help="Only citing works published from this date (YYYY-MM-DD)."
    ),
    max_citing: int = typer.Option(
        2000,
        "--max-citing",
        help="Cap of citing works fetched per paper (newest first; 1 call per 100).",
    ),
    s2: bool = typer.Option(
        False,
        "--s2",
        help="Enrich with Semantic Scholar: real publication date and influential citations.",
    ),
    export: Optional[Path] = typer.Option(
        None, "--export", help="Save the profiles and series to .json or .csv."
    ),
) -> None:
    """Dated citation series per paper: recent windows, acceleration and rate."""
    if bucket not in BUCKETS:
        raise typer.BadParameter(f"--bucket must be one of: {', '.join(BUCKETS)}")
    if since and parse_date(since) is None:
        raise typer.BadParameter("--since must be a date in YYYY-MM-DD format")
    if export and export.suffix.lower() not in {".json", ".csv"}:
        raise typer.BadParameter("Export path must end in .json or .csv")

    wanted = [_short_id(i) for i in (ids or [])]
    if from_export:
        wanted.extend(_ids_from_export(from_export))
    wanted = list(dict.fromkeys(i for i in wanted if i))
    if not wanted:
        err.print("[red]Error:[/red] give at least one work ID or --from-export.")
        raise typer.Exit(1)

    today = date.today()
    # A --since inside the last 180 days cuts the baseline window short, so the
    # previous-90-day count and the acceleration would be misleading: blank them.
    since_date = parse_date(since) if since else None
    baseline_ok = since_date is None or since_date <= today - timedelta(days=180)
    settings = load_settings()
    rows: list[dict] = []
    try:
        with _make_client() as client:
            works = client.fetch_works_by_ids(wanted)
            missing = set(wanted) - {_short_id(w.id) for w in works}
            if missing:
                err.print(f"[yellow]Not found in OpenAlex:[/yellow] {', '.join(sorted(missing))}")
            with console.status(f"Fetching citing works for {len(works)} paper(s)…"):
                for w in works:
                    dates = client.fetch_citing_dates(
                        w.id, since=since, max_results=max_citing
                    )
                    profile = build_profile(dates, today, bucket)
                    rows.append(
                        {
                            "id": _short_id(w.id),
                            "title": w.title,
                            "doi": w.doi,
                            "publication_date": w.publication_date,
                            "best_publication_date": w.publication_date,
                            "cited_by_count": w.cited_by_count,
                            "fwci": w.fwci,
                            "citing_fetched": profile.n_citing,
                            "citing_dated": profile.n_dated,
                            "citing_placeholder_date": profile.n_placeholder,
                            "citing_undated": profile.n_undated,
                            "citing_future_date": profile.n_future,
                            "truncated": profile.n_citing >= max_citing,
                            "first_citation": profile.first_citation,
                            "last_30d": profile.last_30d,
                            "last_90d": profile.last_90d,
                            "prev_90d": profile.prev_90d if baseline_ok else None,
                            "acceleration": profile.acceleration if baseline_ok else None,
                            "cites_per_month": None,
                            "s2_publication_date": None,
                            "s2_citation_count": None,
                            "s2_influential_citation_count": None,
                            "s2_matched_by": None,
                            "bucket": bucket,
                            "series": profile.series,
                        }
                    )
    except OpenAlexError as e:
        err.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    if not rows:
        err.print("[yellow]No works to profile.[/yellow]")
        raise typer.Exit(1)

    if s2:
        from .s2 import S2Client, S2Error

        with S2Client(api_key=settings.s2_api_key) as s2_client:
            with console.status("Enriching with Semantic Scholar…"):
                for row in rows:
                    try:
                        paper = s2_client.lookup(row["doi"], row["title"])
                    except S2Error as e:
                        err.print(f"[yellow]S2 skipped for {row['id']}:[/yellow] {e}")
                        continue
                    if paper is None:
                        continue
                    row["s2_publication_date"] = paper.publication_date
                    row["s2_citation_count"] = paper.citation_count
                    row["s2_influential_citation_count"] = paper.influential_citation_count
                    row["s2_matched_by"] = paper.matched_by
                    if paper.publication_date:
                        row["best_publication_date"] = paper.publication_date

    # Rate since publication, on the best date available (S2's when present). With
    # --since or a truncated fetch the fetched count is partial, so use the total.
    for row in rows:
        row["cites_per_month"] = cites_per_month(
            row["cited_by_count"], parse_date(row["best_publication_date"]), today
        )

    table = Table(
        title=f"Citation series ({bucket} buckets, as of {today.isoformat()})",
        header_style="bold cyan",
    )
    table.add_column("ID", style="dim")
    table.add_column("Title", overflow="fold", max_width=40)
    table.add_column("Published", justify="right")
    table.add_column("Cites", justify="right", style="green")
    table.add_column("30d", justify="right")
    table.add_column("90d", justify="right")
    table.add_column("Prev 90d", justify="right")
    table.add_column("Accel", justify="right")
    table.add_column("Cites/mo", justify="right")
    if s2:
        table.add_column("Influential", justify="right")
    for row in rows:
        cells = [
            row["id"],
            row["title"],
            _fmt(row["best_publication_date"]),
            _fmt(row["cited_by_count"]) + ("+" if row["truncated"] else ""),
            _fmt(row["last_30d"]),
            _fmt(row["last_90d"]),
            _fmt(row["prev_90d"]),
            "—" if row["acceleration"] is None else f"{row['acceleration']:.2f}x",
            _fmt(row["cites_per_month"]),
        ]
        if s2:
            cells.append(_fmt(row["s2_influential_citation_count"]))
        table.add_row(*cells)
    console.print(table)

    excluded = sum(
        r["citing_placeholder_date"] + r["citing_undated"] + r["citing_future_date"]
        for r in rows
    )
    if excluded:
        console.print(
            f"[dim]{excluded} citing work(s) left out of the windows "
            "(placeholder Jan-1, missing or future dates).[/dim]"
        )

    if export:
        if export.suffix.lower() == ".csv":
            out = [{**r, "series": series_str(r["series"])} for r in rows]
        else:
            out = rows
        _export(out, export)
        console.print(f"[green]Exported:[/green] {export}")


@app.command()
def whoami() -> None:
    """Show which credentials the CLI detects in .env."""
    s = load_settings()
    console.print(f"[bold]openalex-cli[/bold] v{__version__}")
    console.print(f"OPENALEX_API_KEY: {'✓ detected' if s.openalex_api_key else '✗ missing'}")
    console.print(f"OPENAI_API_KEY:   {'✓ detected' if s.openai_api_key else '✗ missing'}")
    console.print(f"Embedding model: {s.openai_embed_model}")
    console.print(f"Description model: {s.openai_describe_model}")
    console.print(f"mailto (polite pool): {s.mailto or '—'}")
    console.print(f"S2_API_KEY:       {'✓ detected' if s.s2_api_key else '✗ missing (optional)'}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
