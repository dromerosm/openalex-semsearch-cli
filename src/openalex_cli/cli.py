"""Interfaz de línea de comandos `oa`."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .client import MAX_IDS_PER_FILTER, OpenAlexClient, OpenAlexError, Work
from .config import load_settings

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="CLI para OpenAlex: búsqueda semántica de artículos y análisis de clusters por impacto.",
)
console = Console()
err = Console(stderr=True)

def _build_filter(
    user_filter: Optional[str],
    year: Optional[int],
    from_year: Optional[int],
    to_year: Optional[int],
) -> Optional[str]:
    """Combina el --filter del usuario con un filtro de fecha sobre publication_year.

    `publication_year` es válido server-side en búsqueda semántica y léxica
    (a diferencia de from/to_publication_date, que la semántica rechaza).
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
    """Comprueba el año en cliente (para works traídos por ID, sin filtro server-side)."""
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
    """Serie de citas por año, compacta para CSV: '2026:2;2025:5'."""
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
            # impacto
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
            # acceso / autoría
            "source": w.source,
            "is_oa": w.is_oa,
            "oa_status": w.oa_status,
            "authors": "; ".join(w.authors[:8]),
            "institutions": "; ".join(dict.fromkeys(w.institutions)),
            "countries": "; ".join(dict.fromkeys(w.countries)),
            "doi": w.doi,
            # abstract reconstruido (no full text); ya viene en la respuesta bulk.
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
        raise typer.BadParameter("El export debe terminar en .json o .csv")


def _pct(value: float | None) -> str:
    """Percentil normalizado 0-1 como porcentaje."""
    return "—" if value is None else f"{value * 100:.0f}%"


def _print_works_table(works: list[Work], title: str) -> None:
    table = Table(title=title, show_lines=False, header_style="bold cyan")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Título", overflow="fold", max_width=52)
    table.add_column("Año", justify="right")
    table.add_column("Citas", justify="right", style="green")
    table.add_column("FWCI", justify="right")
    table.add_column("Pctl", justify="right", header_style="bold cyan")  # norm percentile
    table.add_column("Field", overflow="fold", max_width=22)
    table.add_column("Topic", overflow="fold", max_width=24)
    for i, w in enumerate(works, 1):
        # Marca de impacto destacado: ★ top-1%, ▲ top-10%.
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
    query: str = typer.Argument(..., help="Texto de búsqueda (lenguaje natural)."),
    limit: int = typer.Option(25, "--limit", "-n", help="Número de artículos a recuperar."),
    lexical: bool = typer.Option(
        False, "--lexical", help="Usar full-text léxico en vez de búsqueda semántica."
    ),
    filters: Optional[str] = typer.Option(
        None, "--filter", help="Filtro OpenAlex, ej: 'publication_year:>2020,is_oa:true'."
    ),
    year: Optional[int] = typer.Option(None, "--year", help="Año de publicación exacto."),
    from_year: Optional[int] = typer.Option(
        None, "--from-year", help="Desde este año (inclusive). Ignorado si se pasa --year."
    ),
    to_year: Optional[int] = typer.Option(
        None, "--to-year", help="Hasta este año (inclusive). Ignorado si se pasa --year."
    ),
    min_impact: bool = typer.Option(
        True,
        "--min-impact/--no-min-impact",
        help="Solo papers con ≥1 cita y FWCI con valor (por defecto activado).",
    ),
    sort: Optional[str] = typer.Option(
        None, "--sort", help="Orden, ej: 'cited_by_count:desc'."
    ),
    export: Optional[Path] = typer.Option(
        None, "--export", help="Guardar resultados en .json o .csv."
    ),
    raw: bool = typer.Option(
        False,
        "--raw",
        help="Con --export .json, volcar el objeto OpenAlex completo (todos los campos).",
    ),
) -> None:
    """Busca artículos en OpenAlex y muestra su impacto (citas, FWCI, percentil)."""
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
        err.print("[yellow]Sin resultados.[/yellow]")
        raise typer.Exit(0)

    mode = "semántica" if semantic else "léxica"
    _print_works_table(works, f"OpenAlex — búsqueda {mode}: '{query}' ({len(works)} works)")

    if export:
        if raw:
            if export.suffix.lower() != ".json":
                raise typer.BadParameter("--raw requiere un export .json")
            export.write_text(
                json.dumps([w.raw for w in works], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            _export(_works_to_rows(works), export)
        console.print(f"[green]Exportado:[/green] {export}")


@app.command()
def cluster(
    query: str = typer.Argument(..., help="Texto de búsqueda semántica."),
    limit: int = typer.Option(80, "--limit", "-n", help="Artículos a recuperar antes de clusterizar."),
    k: Optional[int] = typer.Option(
        None,
        "--k",
        help="Forzar nº de clusters (KMeans). Si se omite, se descubren con HDBSCAN.",
    ),
    min_cluster_size: int = typer.Option(
        2,
        "--min-cluster-size",
        help="HDBSCAN: tamaño mínimo de cluster. Súbelo para grupos más grandes.",
    ),
    reduce: str = typer.Option(
        "auto",
        "--reduce",
        help="Reducción antes de HDBSCAN: auto (def.: pca si N<50, umap si no), umap, pca o none.",
    ),
    describe: bool = typer.Option(
        False,
        "--describe",
        help="Describir cada cluster con GPT a partir de los abstracts (usa OpenAI).",
    ),
    describe_model: Optional[str] = typer.Option(
        None,
        "--describe-model",
        help="Modelo para --describe (def.: OPENAI_DESCRIBE_MODEL o gpt-5.4-mini).",
    ),
    lexical: bool = typer.Option(
        False, "--lexical", help="Recuperar con full-text en vez de semántico."
    ),
    filters: Optional[str] = typer.Option(
        None, "--filter", help="Filtro OpenAlex aplicado a la recuperación."
    ),
    year: Optional[int] = typer.Option(None, "--year", help="Año de publicación exacto."),
    from_year: Optional[int] = typer.Option(
        None, "--from-year", help="Desde este año (inclusive). Ignorado si se pasa --year."
    ),
    to_year: Optional[int] = typer.Option(
        None, "--to-year", help="Hasta este año (inclusive). Ignorado si se pasa --year."
    ),
    min_impact: bool = typer.Option(
        True,
        "--min-impact/--no-min-impact",
        help="Solo papers con ≥1 cita y FWCI con valor (por defecto activado).",
    ),
    expand: bool = typer.Option(
        False,
        "--expand",
        help="Ampliar el set con los related_works de cada semilla (traídos en bulk) "
        "para superar el tope de 50 del semántico minimizando llamadas.",
    ),
    export: Optional[Path] = typer.Option(
        None, "--export", help="Guardar works con su cluster en .json o .csv."
    ),
) -> None:
    """Recupera artículos, los agrupa por similitud semántica y resume el impacto por cluster."""
    # Import diferido: sklearn/openai son pesados, solo se cargan para clustering.
    from .clustering import cluster_works, describe_clusters, embed_works

    if reduce not in {"auto", "umap", "pca", "none"}:
        raise typer.BadParameter("--reduce debe ser auto, umap, pca o none")

    settings = load_settings()
    if not settings.has_openai:
        err.print("[red]Error:[/red] falta OPENAI_API_KEY en el .env (necesaria para los embeddings).")
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
                    # Bulk: 1 llamada por cada MAX_IDS_PER_FILTER IDs (no uno por work).
                    n_unique = len(set(related))
                    n_calls = -(-n_unique // MAX_IDS_PER_FILTER)  # ceil
                    extra = client.fetch_works_by_ids(related)
                    # El fetch por ID no aplica filtros server-side: replicamos en
                    # cliente tanto el de impacto como el de año.
                    extra = [w for w in extra if _year_ok(w, year, from_year, to_year)]
                    if min_impact:
                        extra = [
                            w for w in extra if w.cited_by_count > 0 and w.fwci is not None
                        ]
                    works.extend(extra)
                    console.print(
                        f"[dim]Expansión: +{len(extra)} works vía related_works "
                        f"({n_calls} llamada(s) bulk).[/dim]"
                    )
    except OpenAlexError as e:
        err.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    if len(works) < 2:
        err.print(f"[yellow]Solo {len(works)} resultado(s); se necesitan ≥2 para clusterizar.[/yellow]")
        raise typer.Exit(1)

    method = "KMeans (k fijo)" if k else f"HDBSCAN (descubrimiento, reduce={reduce})"
    with console.status(f"Generando embeddings y clusterizando con {method}…"):
        embeddings = embed_works(
            works, settings.openai_api_key, settings.openai_embed_model
        )
        clusters, resolved_k = cluster_works(
            works, embeddings, k=k, min_cluster_size=min_cluster_size, reduce=reduce
        )

    model_used = describe_model or settings.openai_describe_model
    if describe:
        try:
            with console.status(f"Describiendo {resolved_k} clusters con {model_used}…"):
                describe_clusters(clusters, settings.openai_api_key, model_used)
        except Exception as e:  # noqa: BLE001 - mostramos el error del modelo sin abortar
            err.print(f"[yellow]No se pudieron generar descripciones ({e}).[/yellow]")

    n_noise = sum(c.size for c in clusters if c.is_noise)
    noise_note = f" · {n_noise} outliers" if n_noise else ""
    console.print(
        f"\n[bold]{len(works)}[/bold] artículos → [bold]{resolved_k}[/bold] clusters "
        f"vía {method}{noise_note}\n"
    )

    def _label(c) -> str:
        return "outliers" if c.is_noise else f"#{c.label}"

    summary = Table(title=f"Clusters para '{query}'", header_style="bold cyan", show_lines=True)
    summary.add_column("Cluster", justify="right")
    summary.add_column("Nº", justify="right")
    summary.add_column("Citas tot.", justify="right", style="green")
    summary.add_column("FWCI medio", justify="right")
    summary.add_column("Top10%", justify="right")
    summary.add_column("Field / domain dominante", overflow="fold", max_width=26)
    summary.add_column("Topics dominantes", overflow="fold", max_width=30)
    summary.add_column("Artículo representativo", overflow="fold", max_width=34)

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
        console.print("\n[bold cyan]Descripciones[/bold cyan] " f"[dim]({model_used})[/dim]")
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
        console.print(f"\n[green]Exportado:[/green] {export}")


@app.command()
def whoami() -> None:
    """Muestra qué credenciales detecta la CLI en el .env."""
    s = load_settings()
    console.print(f"[bold]openalex-cli[/bold] v{__version__}")
    console.print(f"OPENALEX_API_KEY: {'✓ detectada' if s.openalex_api_key else '✗ ausente'}")
    console.print(f"OPENAI_API_KEY:   {'✓ detectada' if s.openai_api_key else '✗ ausente'}")
    console.print(f"Modelo embeddings: {s.openai_embed_model}")
    console.print(f"Modelo descripción: {s.openai_describe_model}")
    console.print(f"mailto (polite pool): {s.mailto or '—'}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
