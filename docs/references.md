# Referencias

## OpenAlex — LLM Quick Reference (fuente principal)

<https://developers.openalex.org/guides/llm-quick-reference>

Guía oficial de OpenAlex con las reglas de uso de la API. Resumen de los puntos
relevantes para esta CLI y cómo los cumple el código.

### Configuración y autenticación

| Punto de la guía | Valor | Dónde en el código |
|---|---|---|
| Base URL | `https://api.openalex.org` | `client.API_BASE` |
| API key | param `api_key` (clave de openalex.org/settings/api) | `client._common_params` (desde `OPENALEX_API_KEY`) |
| `mailto` | recomendado para el *polite pool* | `client._common_params` (desde `OPENALEX_MAILTO`) |

### Endpoints

Siete endpoints de entidad: `/works`, `/authors`, `/sources`, `/institutions`,
`/topics`, `/publishers`, `/funders`. Esta CLI usa solo **`/works`**.

### Parámetros de consulta (snake_case)

`filter`, `search`, `sort`, `per_page` (**máx 100**), `page`, `sample`, `seed`,
`select`, `group_by`.

### Límites operativos

| Límite | Valor | Cumplimiento |
|---|---|---|
| Tamaño de página | máx **100** | `client.MAX_PER_PAGE = 100` |
| Valores en un OR-filter | máx **100** | `client.MAX_IDS_PER_FILTER = 100` (usado en `fetch_works_by_ids`) |
| Paginación básica | hasta 10.000 results | búsqueda léxica usa **cursor** (`_search_cursor`), no `page`, para no toparse con el límite |
| Muestreo aleatorio | hasta 10.000 | no usado |

### Precios (orientativos)

| Operación | Coste | En esta CLI |
|---|---|---|
| Lookup individual | gratis | — |
| Filtrado por lista | $0.0001/consulta | `fetch_works_by_ids` (OR-filter por IDs) |
| Full-text search | $0.001/consulta | `search` (léxica) y `search.semantic` (semántica) |
| Descarga de PDF | $0.01 c/u | no usado |

Plan: $1/día gratis con key; $0.01/día sin key.

### Buenas prácticas (guía) y cumplimiento

- **Backoff exponencial ante errores** → `client._get` reintenta en 429/5xx
  (`RETRY_STATUS`, `MAX_RETRIES`), respetando `Retry-After`.
- **Usar `select=`** para limitar campos → `client.WORK_FIELDS` (se piden solo los
  campos necesarios; abarata y acelera).
- **Batch de IDs con el operador pipe** (`|`) → `fetch_works_by_ids`
  (`ids.openalex:W1|W2|...`, hasta 100 por llamada).
- **Nunca filtrar por nombres de entidad; resolver a IDs primero** → la CLI no
  filtra por nombres; el clustering por similitud usa embeddings, no nombres.
- **Evitar endpoints deprecados** (p. ej. `/text`) → no se usan.

### Particularidades de la búsqueda semántica (verificado en vivo)

No están todas en la guía general; comprobadas contra la API:

- Parámetro: `search.semantic=<texto>` sobre `/works`.
- **Requiere `api_key`** y tiene coste de full-text (~$0.001/consulta).
- **Máximo 50 results**; **no soporta cursor** (usa `page`/`per_page`).
- **No admite filtros de impacto** (`cited_by_count`, `fwci`) server-side → la CLI
  los aplica en cliente (`client._has_impact`). La búsqueda léxica sí los acepta.

## Otras referencias

- CLI oficial de descarga masiva (no hace búsqueda semántica):
  <https://developers.openalex.org/download/openalex-cli> ·
  [`openalex-official` (PyPI)](https://pypi.org/project/openalex-official/)
- `truststore` (trust store del SO; necesario tras el proxy Zscaler corporativo):
  <https://truststore.readthedocs.io>
- OpenAI Embeddings (modelo `text-embedding-3-small` por defecto):
  <https://platform.openai.com/docs/guides/embeddings>
