# References

## OpenAlex — LLM Quick Reference (primary source)

<https://developers.openalex.org/guides/llm-quick-reference>

OpenAlex's official guide to the API usage rules. Summary of the points relevant to
this CLI and how the code complies with them.

### Configuration and authentication

| Guide point | Value | Where in the code |
|---|---|---|
| Base URL | `https://api.openalex.org` | `client.API_BASE` |
| API key | `api_key` param (key from openalex.org/settings/api) | `client._common_params` (from `OPENALEX_API_KEY`) |
| `mailto` | recommended for the *polite pool* | `client._common_params` (from `OPENALEX_MAILTO`) |

### Endpoints

Seven entity endpoints: `/works`, `/authors`, `/sources`, `/institutions`, `/topics`,
`/publishers`, `/funders`. This CLI uses only **`/works`**.

### Query parameters (snake_case)

`filter`, `search`, `sort`, `per_page` (**max 100**), `page`, `sample`, `seed`,
`select`, `group_by`.

### Operational limits

| Limit | Value | Compliance |
|---|---|---|
| Page size | max **100** | `client.MAX_PER_PAGE = 100` |
| Values in an OR-filter | max **100** | `client.MAX_IDS_PER_FILTER = 100` (used in `fetch_works_by_ids`) |
| Basic pagination | up to 10,000 results | lexical search uses a **cursor** (`_search_cursor`), not `page`, to avoid the limit |
| Random sampling | up to 10,000 | not used |

### Pricing (indicative)

| Operation | Cost | In this CLI |
|---|---|---|
| Single lookup | free | — |
| List filtering | $0.0001/query | `fetch_works_by_ids` (OR-filter by IDs) |
| Full-text search | $0.001/query | `search` (lexical) and `search.semantic` (semantic) |
| PDF download | $0.01 each | not used |

Plan: $1/day free with a key; $0.01/day without a key.

### Best practices (from the guide) and compliance

- **Exponential backoff on errors** → `client._get` retries on 429/5xx
  (`RETRY_STATUS`, `MAX_RETRIES`), honoring `Retry-After`.
- **Use `select=`** to limit fields → `client.WORK_FIELDS` (only the needed fields are
  requested; cheaper and faster).
- **Batch IDs with the pipe operator** (`|`) → `fetch_works_by_ids`
  (`ids.openalex:W1|W2|...`, up to 100 per call).
- **Never filter by entity names; resolve to IDs first** → the CLI does not filter by
  names; similarity clustering uses embeddings, not names.
- **Avoid deprecated endpoints** (e.g. `/text`) → not used.

### Semantic search specifics (verified live)

Not all of these are in the general guide; checked against the API:

- Parameter: `search.semantic=<text>` on `/works`.
- **Requires `api_key`** and has full-text cost (~$0.001/query).
- **Maximum 50 results**; **no cursor support** (uses `page`/`per_page`).
- **Does not accept impact filters** (`cited_by_count`, `fwci`) server-side → the CLI
  applies them client-side (`client._has_impact`). Lexical search does accept them.

## Other references

- Official bulk-download CLI (no semantic search):
  <https://developers.openalex.org/download/openalex-cli> ·
  [`openalex-official` (PyPI)](https://pypi.org/project/openalex-official/)
- `truststore` (OS trust store; required behind corporate TLS-inspecting proxies,
  e.g. Zscaler): <https://truststore.readthedocs.io>
- OpenAI Embeddings (default model `text-embedding-3-small`):
  <https://platform.openai.com/docs/guides/embeddings>
