# Ejemplos

Ejemplo de extremo a extremo con filtro por fecha: **"agentic workflows" en 2026**.

> Datos vía OpenAlex (búsqueda semántica + impacto). Ejecutado el 2026-06-08.
> Los números cambian con el tiempo según OpenAlex actualice citas/FWCI.

## 1. Búsqueda semántica con impacto

```bash
oa search "agentic workflows" --year 2026 -n 15 \
  --export examples/agentic-workflows-2026.json
```

Top 6 (★ = top-1% del campo/año · ▲ = top-10%). Export completo en
[`agentic-workflows-2026.json`](agentic-workflows-2026.json):

| Título | Citas | FWCI | Pctl norm. | Field |
|---|---|---|---|---|
| From prompt injections to protocol exploits: … | 12 | 215 | 100% ★ | Decision Sciences |
| ChemGraph as an agentic framework for computa… | 6 | 31 | 100% ★ | Materials Science |
| The Agent-Centric Enterprise: Why 2–10x Produ… | 1 | 49 | 99% ▲ | Social Sciences |
| Benchmarking LLM-based agents for single-cell… | 2 | 15 | 98% ▲ | Biochemistry, Genetic… |
| SurgRAW: Multi-Agent Workflow With Chain of T… | 2 | 37 | 99% ★ | Computer Science |
| CDAFlow: Enhancing LLM clinical decision-maki… | 2 | 44 | 100% ★ | Decision Sciences |

## 2. Clustering por similitud semántica + impacto

Por defecto el nº de clusters se **descubre con HDBSCAN** (sin fijar `k`, con PCA
previo); los artículos que no forman grupo denso se marcan como *outliers*.
`--describe` genera una síntesis de cada cluster con GPT a partir de los abstracts.

```bash
oa cluster "agentic workflows" --year 2026 -n 30 --expand --describe \
  --export examples/agentic-workflows-2026-clusters.json
```

Resumen (export con `cluster` y `cluster_description` por artículo en
[`agentic-workflows-2026-clusters.json`](agentic-workflows-2026-clusters.json)):

| Cluster | Nº | Citas tot. | FWCI medio | Top10% | Field dominante |
|---|---|---|---|---|---|
| #0 | 2 | 13 | 126 | 2/2 | Decision Sciences |
| #1 | 4 | 10 | 14 | 4/4 | Materials Science |
| #2 | 2 | 7 | 26 | 2/2 | Biochemistry, Genetics… |
| #5 | 3 | 5 | 31 | 3/3 | Computer Science |
| #3 | 3 | 3 | 20 | 2/3 | Social Sciences |
| #4 | 2 | 2 | 34 | 2/2 | Health Professions |
| outliers | 2 | 2 | 7 | 2/2 | Chemistry |

Descripciones generadas con `gpt-5.4-mini` (extracto):

- **#0** — Flujos de trabajo de agentes LLM y sus desafíos de **seguridad** (prompt
  injection, exploits de protocolo) y **rendimiento** en entornos distribuidos.
- **#1** — Agentes LLM como orquestadores de **flujos científicos y de diseño**
  (química, materiales), combinando modelos con herramientas de simulación/extracción.
- **#2** — Agentes LLM para automatizar y estandarizar pipelines **single-cell**
  (scRNA-seq), hoy manuales y poco reproducibles.
- **#5** — Workflows agénticos con LLMs/VLMs para tareas **clínicas/biomédicas**
  complejas: múltiples agentes y razonamiento encadenado en vez de una sola llamada.
- **#3** — **Automatización de procesos** con agentes autónomos que ejecutan tareas
  de extremo a extremo, no solo asisten.
- **#4** — IA clínica *workflow-native* integrada en la práctica asistencial real
  (EHR/FHIR), de predecir a coordinar acciones.
- **outliers** — 2 artículos genuinamente aislados: uno donde "agents" son **reactivos
  químicos** (falso amigo léxico) y un paper solitario de **multi-agent RL**.

> **Nota sobre outliers.** HDBSCAN sobre los embeddings de 1536 dims sin reducir
> (`--reduce none`) marcaba **7/18** como outliers. Al analizarlos, varios tenían
> similitud coseno 0.52–0.56 con clusters concretos: no eran outliers reales, sino un
> artefacto de la maldición de la dimensionalidad. Reduciendo dimensionalidad antes de
> HDBSCAN (aquí `--reduce auto` → PCA, por N<50) quedan **2 outliers**, ambos
> verificados como genuinos (similitud ≤0.51, sin vecino denso). En datasets grandes
> `auto` usa **UMAP** (mejor estructura): p. ej. CRISPR (N=120) pasó de 64 a 15 outliers.

## Campos recuperados por artículo

Cada work se recupera **en bloque** (sin llamadas por artículo) con todo lo relevante.
El export estructurado (`.json`/`.csv`) incluye:

- **Identidad**: `id`, `doi`, `title`, `type`, `language`, `publication_date`, `year`.
- **Impacto**: `cited_by_count`, `fwci`, `percentile_year`, `norm_percentile`,
  `is_top_10_percent`, `is_top_1_percent`, `referenced_works_count`,
  `counts_by_year` (serie de citas por año).
- **Topics / fields**: `topic` (+`topic_score`), `subfield`, `field`, `domain`,
  `keywords`, `sdgs` (Sustainable Development Goals).
- **Acceso / autoría**: `source`, `is_oa`, `oa_status`, `authors`, `institutions`,
  `countries`.
- **Texto**: `abstract` (reconstruido; no full text). OpenAlex no tiene abstract para
  todos los works, así que algunos quedan vacíos (`has_abstract: false` en origen).

Para volcar el **objeto OpenAlex completo** (biblio, ids alternativos, todas las
locations, mesh, grants, apc…):

```bash
oa search "agentic workflows" --year 2026 -n 15 --raw \
  --export examples/agentic-workflows-2026-raw.json
```

## Filtro por fecha

Las opciones de fecha actúan sobre `publication_year` (válido server-side tanto en
búsqueda semántica como léxica):

| Opción | Filtro generado |
|---|---|
| `--year 2026` | `publication_year:2026` |
| `--from-year 2024` | `publication_year:>2023` (≥ 2024) |
| `--to-year 2025` | `publication_year:<2026` (≤ 2025) |
| `--from-year 2024 --to-year 2026` | rango 2024–2026 |

En `--expand`, los `related_works` se traen por ID (sin filtro server-side), así que
el filtro de año —igual que el de impacto— se aplica en cliente para no colar works
de otros años.
