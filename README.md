# openalex-cli (`oa`)

CLI para [OpenAlex](https://openalex.org) orientada a investigación: **búsqueda semántica**
de artículos, recuperación de su **impacto** (citas, FWCI, percentil) y **análisis de clusters**
por similitud semántica.

> Reglas de la API y cumplimiento: ver [docs/references.md](docs/references.md)
> (basado en la [LLM Quick Reference](https://developers.openalex.org/guides/llm-quick-reference) oficial).

## ¿Por qué no la CLI oficial?

OpenAlex publica una CLI oficial ([`openalex-official`](https://pypi.org/project/openalex-official/)),
pero está pensada para **descarga masiva** de metadata/PDF/TEI-XML por filtros o DOIs. No hace
búsqueda semántica ni clustering. Esta CLI cubre ese hueco apoyándose en:

- el parámetro `search.semantic` de la API de OpenAlex (embeddings GTE-Large, beta, ~$0.001/consulta);
- embeddings de OpenAI + KMeans para agrupar los resultados y resumir su impacto.

## Requisitos

- Python ≥ 3.14
- Un `.env` en la raíz con:

```dotenv
OPENALEX_API_KEY=...        # requerida para búsqueda semántica
OPENAI_API_KEY=...          # requerida para el comando `cluster`
# opcionales:
OPENALEX_MAILTO=tu@email    # entra en el "polite pool" de OpenAlex
OPENAI_EMBED_MODEL=text-embedding-3-small
OPENAI_DESCRIBE_MODEL=gpt-5.4-mini   # modelo para `cluster --describe`
```

## Instalación

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -e .
```

## Uso

```bash
# Comprobar credenciales detectadas
.venv/bin/oa whoami

# Búsqueda semántica con impacto
.venv/bin/oa search "graph neural networks for drug discovery" -n 25

# Filtrar y ordenar; exportar a CSV/JSON
.venv/bin/oa search "kelp biomechanics" -n 50 \
  --filter "publication_year:>2020,is_oa:true" \
  --sort cited_by_count:desc \
  --export resultados.csv

# Filtro por fecha (atajos sobre publication_year)
.venv/bin/oa search "agentic workflows" --year 2026
.venv/bin/oa search "diffusion models" --from-year 2023 --to-year 2025

# Búsqueda léxica (full-text) en vez de semántica
.venv/bin/oa search "transformer architecture" --lexical

# Clusterizar: por defecto descubre el nº de clusters con HDBSCAN
.venv/bin/oa cluster "large language models for code" -n 80
# Forzar nº de clusters con KMeans
.venv/bin/oa cluster "CRISPR off-target effects" -n 100 --k 5 --export clusters.json

# Describir cada cluster con GPT a partir de los abstracts
.venv/bin/oa cluster "agentic workflows" --year 2026 -n 30 --expand --describe

# Ampliar el set más allá del tope de 50 del semántico, en bulk (1 llamada/100 works)
.venv/bin/oa cluster "agentic workflows" --year 2026 -n 30 --expand
```

(Activa el venv con `source .venv/bin/activate` y podrás omitir el prefijo `.venv/bin/`.)

Ejemplo completo ejecutado en [examples/](examples/README.md).

## Comandos

| Comando | Qué hace |
|---|---|
| `oa search <query>` | Recupera artículos (semántico por defecto) con citas, FWCI y percentil. |
| `oa cluster <query>` | Recupera, embebe (OpenAI), agrupa con KMeans y resume el impacto por cluster. |
| `oa whoami` | Muestra qué credenciales detecta en el `.env`. |

### Datos recuperados por artículo

Cada work se trae **en bloque** (sin llamadas por artículo) con todo lo relevante.
`select` no añade llamadas, así que se pide el conjunto completo:

- **Impacto**: `cited_by_count`, `fwci` (*Field-Weighted Citation Impact*; 1.0 = media
  del campo), `cited_by_percentile_year`, `citation_normalized_percentile` (+ flags
  **top-1% / top-10%**), `referenced_works_count`, y `counts_by_year` (serie de citas
  por año).
- **Topics / fields** (jerarquía `domain > field > subfield > topic`): `primary_topic`
  con `topic_score`, además de `field`, `subfield`, `domain`, `keywords` y
  `sustainable_development_goals`.
- **Metadatos**: `type`, `language`, `publication_date`, `source`, `is_oa`/`oa_status`,
  autores, instituciones y países.
- **Texto**: `abstract` (reconstruido desde el índice invertido; **no** full text).
  Algunos works no tienen abstract en OpenAlex y quedan vacíos.

En las tablas, ★ marca top-1% y ▲ top-10% (percentil normalizado por campo y año).
Con `oa search ... --raw --export f.json` se vuelca el **objeto OpenAlex completo**
(biblio, ids alternativos, todas las locations, mesh, grants, apc…) sin llamadas extra.

### Filtro de impacto (`--min-impact`)

Por defecto `search` y `cluster` solo devuelven papers con **≥1 cita y FWCI con valor**
(`cited_by_count:>0,fwci:>0`). Desactívalo con `--no-min-impact`.

- En búsqueda **léxica** se aplica como filtro server-side (no trae works descartados).
- En búsqueda **semántica** la API no admite esos filtros, así que se traen los
  candidatos (máx 50) y se filtran en cliente. Lo mismo para los works de `--expand`
  (se piden por ID y se filtran tras el fetch bulk).

### Clustering: descubrimiento vs. k fijo

- **Sin `--k`** → **HDBSCAN**: descubre el nº de clusters por densidad y marca como
  *outliers* los artículos que no forman grupo (no los fuerza a un cluster).
  Ajusta la granularidad con `--min-cluster-size` (def. 2; súbelo para grupos mayores).
- **Con `--k N`** → **KMeans** con ese k (override explícito).

**Reducción de dimensionalidad (`--reduce`).** HDBSCAN sobre embeddings de 1536 dims
sobre-marca outliers (la densidad no es fiable en alta dimensión: en un test pasó del
60% al 16% de falsos outliers al reducir). Por eso se reduce antes de clusterizar:

- `auto` (def.) — **PCA** si N<50 (estable en datasets pequeños), **UMAP** si N≥50.
- `umap` — preserva mejor la estructura local (estándar BERTopic); necesita N suficiente.
- `pca` — lineal y estable, sin coste de cómputo alto.
- `none` — sobre los embeddings completos (no recomendado).

Los clusters se ordenan por **citas totales** y muestran su **field/domain y topics
dominantes**, cuántos works están en el top-10% de su campo, y el artículo más
representativo (el más cercano al centroide).

### Describir clusters con GPT (`--describe`)

`oa cluster ... --describe` genera, para cada cluster, una síntesis en español a
partir de los **abstracts** de sus artículos (una llamada por cluster). El modelo es
`OPENAI_DESCRIBE_MODEL` (def. `gpt-5.4-mini`), o `--describe-model <id>`. Las
descripciones se imprimen bajo la tabla y se añaden al export como
`cluster_description`.

### Minimizar llamadas a la API (bulk)

La CLI evita patrones N+1:

- La **búsqueda semántica** devuelve los works completos (con impacto) en **1 llamada**
  (máx 50 results; la léxica trae hasta 100/llamada vía cursor).
- Los **embeddings** de OpenAI se piden **en batch**.
- `--expand` usa los `related_works` (que ya vienen en la respuesta) y los recupera con el
  OR-filter `ids.openalex:W1|W2|...` → **1 llamada por cada 100 works** en vez de uno por work.
  Reutilizable como `OpenAlexClient.fetch_works_by_ids(ids)`.

## Citar OpenAlex

Esta CLI usa los datos de OpenAlex. Si publicas resultados obtenidos con ella, cita:

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
