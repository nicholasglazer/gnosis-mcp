---
title: REST API Reference
category: docs
audience: all
relates_to:
  - README.md
  - docs/tools.md
  - docs/config.md
  - docs/cli.md
---

# REST API Reference

gnosis-mcp ships an optional HTTP/JSON mirror of its MCP tools. It lives
alongside the MCP streamable-HTTP endpoint on the same port — no extra
process, no extra deploy target.

Enable with `--rest` on `gnosis-mcp serve` or `GNOSIS_MCP_REST=true`.

## Base

- **Transport**: HTTPS (deploy behind a reverse proxy — the server itself
  serves plain HTTP).
- **Content-Type**: `application/json` on all JSON endpoints.
- **Auth**: optional Bearer token via `GNOSIS_MCP_API_KEY`. When unset,
  endpoints are open (fine for localhost development).
- **Public paths**: `/health` is the only unauthenticated path, and there is
  no setting to add more. `GNOSIS_MCP_PUBLIC_PATHS` is **not implemented** —
  see [config.md](config.md).
- **CORS**: off by default. Set `GNOSIS_MCP_CORS_ORIGINS=*` or a comma list
  of origins to enable.
- **Rate-limit / observability**: not built in. Put the usual Nginx /
  Cloudflare / Fly layer in front.

---

## Authentication

```http
GET /api/search?q=… HTTP/1.1
Authorization: Bearer sk_prod_xxxxxxxxxxxxxxxxxxxxxxxx
```

Comparison uses `secrets.compare_digest` — timing-safe. Missing or wrong
token → `401` with `{"error":"Unauthorized"}`.

---

## Endpoints

### `GET /health`

Server heartbeat. Always public. Use for liveness / readiness probes.

```json
{
  "status": "ok",
  "version": "0.16.1",
  "backend": "sqlite",
  "docs": 412,
  "chunks": 1_247,
  "search_stats": {
    "total": 38,
    "misses": 2,
    "hybrid": 21,
    "keyword": 17
  }
}
```

`docs` counts distinct `file_path` values; `chunks` counts post-split rows.
`search_stats` is a process-lifetime counter of search calls — `total`,
`misses` (queries that returned nothing), and a breakdown by `hybrid` /
`keyword` mode. It resets when the server restarts.

### `GET /api/search`

Keyword / hybrid search mirror of the `search_docs` MCP tool.

**Query parameters**

| Name | Type | Default | Notes |
| ---- | ---- | ------- | ----- |
| `q` | `string` | — | The search text. Missing/empty → `400`. |
| `limit` | `int` | `10` | Clamped to `GNOSIS_MCP_SEARCH_LIMIT_MAX`. |
| `category` | `string` | — | Optional filter. |

Auto-embedding: when a local ONNX provider is configured, the query is
embedded in-process and results are ranked with hybrid RRF.

**Response**

```json
{
  "query": "how does hybrid search work",
  "count": 1,
  "results": [
    {
      "file_path": "docs/backends.md",
      "title": "Backends",
      "category": "docs",
      "content_preview": "…preview…",
      "score": 0.049,
      "highlight": "…<mark>hybrid</mark>…"
    }
  ]
}
```

### `GET /api/docs/{path}`

Reassemble a document. `path` is URL-encoded.

```bash
curl -s "http://localhost:8000/api/docs/docs%2Ftools.md" \
  -H "Authorization: Bearer $GNOSIS_MCP_API_KEY"
```

Response shape matches the MCP `get_doc` tool.

### `GET /api/docs/{path}/related`

Neighbours of `{path}`.

**Query parameters**

| Name | Type | Default |
| ---- | ---- | ------- |
| `depth` | `int` | `1` |
| `relation_type` | `string` | — |
| `include_titles` | `bool` | `false` |

### `GET /api/categories`

List categories with their doc counts. Useful for populating filter UIs.

```json
[
  {"category": "guides", "count": 12},
  {"category": "architecture", "count": 5}
]
```

### `GET /api/context`

Usage-weighted orientation summary (topical or global).

**Query parameters**

| Name | Type | Default |
| ---- | ---- | ------- |
| `topic` | `string` | — |
| `limit` | `int` | `10` |
| `category` | `string` | — |

### `GET /api/graph/stats`

Knowledge-graph topology. Shape matches the `get_graph_stats` MCP tool.

```bash
curl -s "http://localhost:8000/api/graph/stats?category=docs"
```

---

## Errors

All errors return a JSON body with a single `error` key. The string is
human-readable, not a stable machine code — `401` is exactly `Unauthorized`,
while validation and lookup failures carry a descriptive message such as
`Query parameter 'q' is required` or `Not found: docs/tools.md`.

```json
{"error": "Not found: docs/tools.md"}
```

| Status | Meaning |
| ------ | ------- |
| `400` | Missing/invalid parameter. |
| `401` | Auth required or token invalid. |
| `404` | Document not found. |
| `413` | Payload too large (future — size cap on write endpoints). |
| `500` | Internal — check server logs. |

---

## Example: private intranet read-only mirror

```bash
# .env
GNOSIS_MCP_DATABASE_URL=postgresql://gnosis:pw@db:5432/gnosis
GNOSIS_MCP_EMBED_PROVIDER=local
GNOSIS_MCP_REST=true
GNOSIS_MCP_API_KEY=sk_prod_xxxxxxxxxxxxxxxxxxxxxxxx
GNOSIS_MCP_HOST=0.0.0.0
GNOSIS_MCP_CORS_ORIGINS=https://intranet.example.com

# compose.yaml — alongside your own front-end:
services:
  gnosis:
    image: ghcr.io/nicholasglazer/gnosis-mcp:latest
    command: gnosis-mcp serve --transport streamable-http --rest
    env_file: .env
    ports: ["8000:8000"]
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/health"]
      interval: 30s
```

---

## See also

- [Configuration](config.md) — env vars that shape these endpoints.
- [MCP tools](tools.md) — same surface, but over MCP stdio / streamable.
- [CLI](cli.md) — populate the index that REST / MCP read from.
