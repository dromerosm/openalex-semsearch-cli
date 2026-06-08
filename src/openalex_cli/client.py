"""Cliente delgado sobre la API REST de OpenAlex.

Documenta los dos modos de búsqueda relevantes:
  - semántica (embeddings, beta): parámetro `search.semantic`
  - léxica / full-text:           parámetro `search`
Ambos sobre el endpoint /works. Según la guía oficial, la full-text search
(semántica o léxica) cuesta ~$0.001/consulta; el filtrado por lista (p. ej.
`fetch_works_by_ids`) ~$0.0001/consulta. La semántica requiere api_key.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from .ssl_setup import ensure_system_trust

API_BASE = "https://api.openalex.org"

# Límites de la API (ver developers.openalex.org/guides/llm-quick-reference).
MAX_PER_PAGE = 100  # tamaño máximo de página
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_RETRIES = 4

# Campos que pedimos a OpenAlex. Seleccionar campos no añade llamadas (todo viene en
# la misma respuesta); pedimos todo lo relevante para topics/fields, impacto y metadatos.
WORK_FIELDS = [
    "id",
    "doi",
    "display_name",
    "publication_year",
    "publication_date",
    "type",
    "language",
    # --- impacto ---
    "cited_by_count",
    "fwci",  # field-weighted citation impact
    "cited_by_percentile_year",
    "citation_normalized_percentile",  # value + flags top 1% / 10%
    "counts_by_year",  # serie temporal de citas por año
    "referenced_works_count",
    "relevance_score",
    # --- topics / fields (jerarquía domain > field > subfield > topic) ---
    "primary_topic",
    "topics",
    "keywords",
    "sustainable_development_goals",
    # --- ubicación / acceso ---
    "primary_location",
    "best_oa_location",
    "open_access",
    # --- autoría ---
    "authorships",
    # --- texto / enlaces ---
    "abstract_inverted_index",
    "related_works",  # IDs precalculados por OpenAlex; vienen gratis en la respuesta
]

# OpenAlex acepta hasta 100 valores en un OR-filter (ids.openalex:W1|W2|...).
MAX_IDS_PER_FILTER = 100

# Filtro de impacto: ≥1 cita y FWCI con valor. Solo válido server-side en léxica;
# la búsqueda semántica no lo admite (se aplica con _has_impact en cliente).
IMPACT_FILTER = "cited_by_count:>0,fwci:>0"


@dataclass
class Work:
    """Representación normalizada de un work de OpenAlex."""

    id: str
    title: str
    year: int | None
    publication_date: str | None
    type: str | None
    language: str | None
    # --- impacto ---
    cited_by_count: int
    fwci: float | None
    percentile: float | None  # cited_by_percentile_year.value
    norm_percentile: float | None  # citation_normalized_percentile.value
    is_top_10_percent: bool
    is_top_1_percent: bool
    referenced_works_count: int
    counts_by_year: list[dict]  # [{"year": int, "cited_by_count": int}, ...]
    relevance: float | None
    doi: str | None
    # --- topics / fields ---
    topic: str | None
    topic_id: str | None
    topic_score: float | None
    subfield: str | None
    field: str | None
    domain: str | None
    keywords: list[str]
    sdgs: list[str]
    # --- acceso / autoría ---
    source: str | None
    is_oa: bool
    oa_status: str | None
    authors: list[str]
    institutions: list[str]
    countries: list[str]
    abstract: str | None
    related_works: list[str] = field(default_factory=list)
    raw: dict = field(repr=False, default_factory=dict)

    @property
    def text_for_embedding(self) -> str:
        parts = [self.title or ""]
        if self.abstract:
            parts.append(self.abstract)
        return "\n".join(p for p in parts if p).strip()


def _reconstruct_abstract(inverted: dict | None) -> str | None:
    """OpenAlex entrega el abstract como índice invertido {palabra: [posiciones]}."""
    if not inverted:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted.items():
        for i in idxs:
            positions.append((i, word))
    if not positions:
        return None
    positions.sort(key=lambda x: x[0])
    return " ".join(word for _, word in positions)


def _name(obj: dict | None) -> str | None:
    return (obj or {}).get("display_name")


def _parse_work(item: dict) -> Work:
    primary_topic = item.get("primary_topic") or {}
    primary_location = item.get("primary_location") or {}
    open_access = item.get("open_access") or {}
    authorships = item.get("authorships", [])

    authors = [_name(a.get("author")) for a in authorships]
    institutions = [
        _name(inst) for a in authorships for inst in (a.get("institutions") or [])
    ]
    countries = [c for a in authorships for c in (a.get("countries") or [])]

    pct = item.get("cited_by_percentile_year") or {}
    norm = item.get("citation_normalized_percentile") or {}
    return Work(
        id=item.get("id", ""),
        title=item.get("display_name") or "(sin título)",
        year=item.get("publication_year"),
        publication_date=item.get("publication_date"),
        type=item.get("type"),
        language=item.get("language"),
        cited_by_count=item.get("cited_by_count", 0) or 0,
        fwci=item.get("fwci"),
        percentile=pct.get("value") if isinstance(pct, dict) else None,
        norm_percentile=norm.get("value") if isinstance(norm, dict) else None,
        is_top_10_percent=bool(norm.get("is_in_top_10_percent")),
        is_top_1_percent=bool(norm.get("is_in_top_1_percent")),
        referenced_works_count=item.get("referenced_works_count", 0) or 0,
        counts_by_year=item.get("counts_by_year") or [],
        relevance=item.get("relevance_score"),
        doi=item.get("doi"),
        topic=primary_topic.get("display_name"),
        topic_id=primary_topic.get("id"),
        topic_score=primary_topic.get("score"),
        subfield=_name(primary_topic.get("subfield")),
        field=_name(primary_topic.get("field")),
        domain=_name(primary_topic.get("domain")),
        keywords=[k.get("display_name") for k in item.get("keywords", []) if k.get("display_name")],
        sdgs=[g.get("display_name") for g in item.get("sustainable_development_goals", []) if g.get("display_name")],
        source=_name(primary_location.get("source")),
        is_oa=bool(open_access.get("is_oa")),
        oa_status=open_access.get("oa_status"),
        authors=[a for a in authors if a],
        institutions=[i for i in institutions if i],
        countries=countries,
        abstract=_reconstruct_abstract(item.get("abstract_inverted_index")),
        related_works=item.get("related_works") or [],
        raw=item,
    )


def _has_impact(work: Work) -> bool:
    """≥1 cita y FWCI con valor (filtro de impacto aplicado en cliente)."""
    return work.cited_by_count > 0 and work.fwci is not None


class OpenAlexError(RuntimeError):
    pass


class OpenAlexClient:
    def __init__(
        self,
        api_key: str | None = None,
        mailto: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.mailto = mailto
        ensure_system_trust()
        self._client = httpx.Client(
            base_url=API_BASE,
            timeout=timeout,
            headers={"User-Agent": f"openalex-cli (mailto:{mailto})" if mailto else "openalex-cli"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OpenAlexClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _common_params(self) -> dict[str, str]:
        params: dict[str, str] = {}
        if self.api_key:
            params["api_key"] = self.api_key
        if self.mailto:
            params["mailto"] = self.mailto
        return params

    def search_works(
        self,
        query: str,
        *,
        semantic: bool = True,
        limit: int = 50,
        filters: str | None = None,
        sort: str | None = None,
        min_impact: bool = False,
        full: bool = False,
    ) -> list[Work]:
        """Busca works. `semantic=True` usa embeddings; False usa full-text.

        La búsqueda semántica no soporta cursor (máx 50 results) ni los filtros de
        impacto; la léxica sí pagina con cursor y los acepta server-side.

        `min_impact` exige ≥1 cita y FWCI con valor. En léxica se aplica como
        filtro server-side; en semántica se filtra en cliente (tras traer el máximo
        de candidatos), porque la API semántica no admite esos filtros.

        `full=True` omite `select`, de modo que OpenAlex devuelve el objeto completo
        (todos los campos) en `Work.raw` sin llamadas adicionales.
        """
        if semantic and not self.api_key:
            raise OpenAlexError(
                "La búsqueda semántica requiere OPENALEX_API_KEY en el .env."
            )

        search_param = "search.semantic" if semantic else "search"

        if semantic:
            # Si filtramos en cliente, pedimos el tope (50) para maximizar el yield.
            fetch_n = 50 if min_impact else limit
            works = self._search_paged(
                search_param, query, fetch_n, filters, sort, hard_cap=50, full=full
            )
            if min_impact:
                works = [w for w in works if _has_impact(w)]
            return works[:limit]

        effective = filters
        if min_impact:
            effective = ",".join(c for c in (filters, IMPACT_FILTER) if c)
        return self._search_cursor(search_param, query, limit, effective, sort, full=full)

    def fetch_works_by_ids(self, work_ids: list[str]) -> list[Work]:
        """Trae varios works en bloque con el OR-filter `ids.openalex:W1|W2|...`.

        Una sola llamada por cada 50 IDs (en vez de un GET por work). Acepta IDs
        completos (URL) o cortos (Wxxxx); preserva el orden de entrada.
        """
        short_ids = [wid.rsplit("/", 1)[-1] for wid in work_ids if wid]
        # Dedup preservando orden.
        seen: set[str] = set()
        unique = [i for i in short_ids if not (i in seen or seen.add(i))]

        by_id: dict[str, Work] = {}
        for start in range(0, len(unique), MAX_IDS_PER_FILTER):
            chunk = unique[start : start + MAX_IDS_PER_FILTER]
            params = self._common_params()
            params["filter"] = "ids.openalex:" + "|".join(chunk)
            params["select"] = ",".join(WORK_FIELDS)
            params["per_page"] = str(MAX_IDS_PER_FILTER)
            data = self._get("/works", params)
            for item in data.get("results", []):
                work = _parse_work(item)
                by_id[work.id.rsplit("/", 1)[-1]] = work

        return [by_id[i] for i in unique if i in by_id]

    def _base_params(
        self,
        search_param: str,
        query: str,
        filters: str | None,
        sort: str | None,
        full: bool = False,
    ) -> dict[str, str]:
        params = self._common_params()
        params[search_param] = query
        if not full:  # full omite select -> OpenAlex devuelve el objeto completo
            params["select"] = ",".join(WORK_FIELDS)
        if filters:
            params["filter"] = filters
        if sort:
            params["sort"] = sort
        return params

    def _search_paged(
        self,
        search_param: str,
        query: str,
        limit: int,
        filters: str | None,
        sort: str | None,
        hard_cap: int,
        full: bool = False,
    ) -> list[Work]:
        limit = min(limit, hard_cap)
        results: list[Work] = []
        page = 1
        while len(results) < limit:
            params = self._base_params(search_param, query, filters, sort, full=full)
            params["per_page"] = str(min(limit - len(results), 50))
            params["page"] = str(page)
            data = self._get("/works", params)
            batch = data.get("results", [])
            if not batch:
                break
            results.extend(_parse_work(it) for it in batch)
            page += 1
        return results[:limit]

    def _search_cursor(
        self,
        search_param: str,
        query: str,
        limit: int,
        filters: str | None,
        sort: str | None,
        full: bool = False,
    ) -> list[Work]:
        results: list[Work] = []
        cursor = "*"
        while len(results) < limit:
            params = self._base_params(search_param, query, filters, sort, full=full)
            params["per_page"] = str(min(limit - len(results), MAX_PER_PAGE))
            params["cursor"] = cursor
            data = self._get("/works", params)
            batch = data.get("results", [])
            if not batch:
                break
            results.extend(_parse_work(it) for it in batch)
            cursor = (data.get("meta") or {}).get("next_cursor")
            if not cursor:
                break
        return results[:limit]

    def _get(self, path: str, params: dict[str, str]) -> dict:
        # Backoff exponencial ante 429/5xx, como recomienda la guía oficial.
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = self._client.get(path, params=params)
            except httpx.HTTPError as e:
                last_exc = e
                time.sleep(2**attempt)
                continue

            if resp.status_code in RETRY_STATUS and attempt < MAX_RETRIES - 1:
                retry_after = resp.headers.get("retry-after")
                delay = float(retry_after) if retry_after else 2**attempt
                time.sleep(delay)
                continue

            if resp.status_code == 403:
                raise OpenAlexError(
                    "OpenAlex devolvió 403. Revisa que la api_key sea válida y tenga saldo."
                )
            if resp.status_code >= 400:
                raise OpenAlexError(
                    f"OpenAlex devolvió {resp.status_code}: {resp.text[:300]}"
                )
            return resp.json()

        raise OpenAlexError(f"Error de red contra OpenAlex tras reintentos: {last_exc}")
