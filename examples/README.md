# Examples

Worked, reproducible examples. Each example lives in its own folder with a `README.md`
write-up and the exported data files.

| Example | What it shows |
|---|---|
| [agentic-workflows-2026](agentic-workflows-2026/) | Semantic search + impact and cluster discovery (HDBSCAN/UMAP) with GPT summaries, filtered to 2026. |

## Folder layout

```
examples/
└── <example-name>/
    ├── README.md      # write-up: commands, tables, findings
    ├── search.json    # `oa search ... --export`
    ├── clusters.json  # `oa cluster ... --export`
    └── raw.json       # `oa search ... --raw --export` (full OpenAlex objects)
```

To add a new example, create `examples/<name>/`, run the `oa` commands with
`--export examples/<name>/<file>.json`, and add a `README.md` plus a row in the table
above.
