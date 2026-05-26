# gnosis-mcp as your self-hosted embeddings service

> v0.14.0+

`POST /v1/embed` makes gnosis-mcp a drop-in OpenAI-shaped embeddings backend for any client that already knows how to talk to `/v1/embeddings`. Same Docker image you already use for docs search — just a different deployment profile.

## When this fits

- You have a backend or RAG pipeline that needs embeddings on a steady basis and the per-token API bill is starting to add up.
- You want your data to stay on your network.
- You want to pick the embedding model (and swap it later) without changing your backend code.
- You're already running gnosis-mcp anyway, so embeddings live next to your docs index for free.

## When it doesn't fit

- You need GPU-class throughput beyond what your server CPU can deliver. Self-hosting embeddings on CPU caps out around 30-100 embeds/sec per process for a 500M-param model.
- You need >100 embeddings/sec sustained from a single instance. (Run multiple instances behind a load balancer instead.)
- You need image / multimodal embeddings. This endpoint is text-only.

## Quick start

```bash
docker run -d \
  --name gnosis-embed \
  -p 8000:8000 \
  -e GNOSIS_MCP_TRANSPORT=streamable-http \
  -e GNOSIS_MCP_REST=true \
  -e GNOSIS_MCP_HOST=0.0.0.0 \
  -e GNOSIS_MCP_EMBED_PROVIDER=local \
  -e GNOSIS_MCP_EMBED_MODEL=intfloat/multilingual-e5-large \
  -e GNOSIS_MCP_EMBED_DIM=1024 \
  -e GNOSIS_MCP_API_KEY="$(openssl rand -hex 32)" \
  -v gnosis-data:/data \
  -v hf-cache:/root/.cache/huggingface \
  ghcr.io/nicholasglazer/gnosis-mcp:latest
```

Health check:

```bash
curl http://localhost:8000/health
```

Embed:

```bash
curl -X POST http://localhost:8000/v1/embed \
  -H "Authorization: Bearer $GNOSIS_MCP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"texts": ["how do I get residency?", "¿cómo obtengo la residencia?"]}'
```

Response:

```json
{
  "model": "intfloat/multilingual-e5-large",
  "dim": 1024,
  "vectors": [[0.012, -0.087, ...], [0.014, -0.082, ...]],
  "usage": {"prompt_tokens": 14, "total_tokens": 14}
}
```

## Choosing a model

| Model | Params | Dim | Multilingual | Notes |
|---|---|---|---|---|
| `MongoDB/mdbr-leaf-ir` (default) | 23M | 384 | English-specialised | Fast on CPU; #1 MTEB ≤100M |
| `intfloat/multilingual-e5-base` | 278M | 768 | 100+ langs | Good balance for non-English |
| `intfloat/multilingual-e5-large` | 560M | 1024 | 100+ langs | Strong multilingual retrieval |
| `BAAI/bge-m3` | 568M | 1024 | 100+ langs | Dense + sparse + multi-vector |
| `intfloat/e5-large-v2` | 335M | 1024 | English | English-only large |

Switch by setting `GNOSIS_MCP_EMBED_MODEL` + `GNOSIS_MCP_EMBED_DIM`. First request after switch downloads the model from HuggingFace into `/root/.cache/huggingface`, so mount that volume to keep it across container restarts.

## OpenAI compatibility note

The endpoint URL and body shape are intentionally OpenAI-shaped (with `texts` as the field name instead of `input` to keep the array-only semantics explicit):

```python
import httpx

resp = httpx.post(
    "http://localhost:8000/v1/embed",
    headers={"Authorization": f"Bearer {api_key}"},
    json={"texts": ["hello"]},
).json()
vector = resp["vectors"][0]
```

If you're migrating from `openai.embeddings.create(model="text-embedding-3-small", input="hello")`, swap the URL and rename the field from `input` to `texts`. The response shape (`model`, `dim`, `vectors`, `usage.prompt_tokens`) matches what most consumers expect.

## Limits

- 256 texts per request (returns 400 if exceeded).
- 50 KB per individual text (returns 400 if exceeded).
- Bearer auth via `GNOSIS_MCP_API_KEY` — required for any non-trusted-network deployment.
- Per-request `model` override is honored, but stays inside the configured `embed_provider`. Cross-provider routing (e.g. switch from local ONNX to OpenAI API mid-request) is not supported.

## Throughput, roughly

On a modern 6-core x86 CPU (e.g. Intel i5-12500), with INT8 quantized ONNX:

| Model | Single-query latency | Batch-32 throughput |
|---|---|---|
| `mdbr-leaf-ir` | 5-15 ms | 200-300/sec |
| `multilingual-e5-base` | 20-50 ms | 80-150/sec |
| `multilingual-e5-large` | 50-150 ms | 30-60/sec |
| `bge-m3` | 80-200 ms | 15-40/sec |

For one-time bulk ingest of 20k chunks with `multilingual-e5-large`: roughly 10-15 minutes on a single CPU.

## Deployment tips

- **Pin CPU cores** with `--cpuset-cpus="8-11"` to keep embedding work from contending with your database for memory bandwidth.
- **Mount `/root/.cache/huggingface`** as a volume so model downloads survive container restarts.
- **Use PostgreSQL backend** (`GNOSIS_MCP_DATABASE_URL=postgresql://...`) for production — concurrent reads + better recovery than SQLite.
- **Set a real `GNOSIS_MCP_API_KEY`** — gnosis-mcp will accept requests without one, but if your instance is reachable from outside your network anyone can use it.
- **Behind a reverse proxy**, expose only `/v1/embed`, `/health`, and (if you want it) `/api/search`. Mount `/mcp` only if you actually need MCP-protocol access.

## What it doesn't do (yet)

- No `/metrics` Prometheus endpoint (planned).
- No batched async API with backpressure (planned).
- No multi-model-in-one-process routing — one model per gnosis-mcp instance.

If you need any of these for a real deployment, file an issue at <https://github.com/nicholasglazer/gnosis-mcp/issues> and tell us what your traffic shape looks like.
