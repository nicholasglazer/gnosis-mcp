# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# gnosis-mcp — self-hosted MCP documentation server
#
# Multi-arch (linux/amd64, linux/arm64). Published to:
#   ghcr.io/nicholasglazer/gnosis-mcp:<tag>   and   :latest
#
# Defaults to streamable-http + REST on :8000, local ONNX embeddings, SQLite
# at /data/docs.db. Mount your docs at /docs and the database at /data.
#
#   docker run -p 8000:8000 \
#     -v "$PWD/docs:/docs:ro" -v gnosis-data:/data \
#     ghcr.io/nicholasglazer/gnosis-mcp:latest
#
# First-run bootstrap (same image, different CMD):
#
#   docker run --rm -v "$PWD/docs:/docs:ro" -v gnosis-data:/data \
#     ghcr.io/nicholasglazer/gnosis-mcp:latest \
#     ingest /docs --embed
# ---------------------------------------------------------------------------

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy only what's needed to install, then the source — preserves the
# 2-layer cache (deps rebuild only on pyproject/lock change).
COPY pyproject.toml README.md LICENSE ./
COPY src ./src

# All production extras. Users who don't want them can build a slimmer
# variant with `--build-arg EXTRAS=embeddings,postgres`.
ARG EXTRAS="embeddings,postgres,web,reranking"
RUN pip install --prefix=/install ".[${EXTRAS}]"

# ---------------------------------------------------------------------------

FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GNOSIS_MCP_HOST=0.0.0.0 \
    GNOSIS_MCP_PORT=8000 \
    GNOSIS_MCP_DATABASE_URL=sqlite:////data/docs.db \
    GNOSIS_MCP_EMBED_PROVIDER=local \
    GNOSIS_MCP_ACCESS_LOG=true

# Runtime deps: libgomp1 for onnxruntime, curl for HEALTHCHECK, ca-certs
# for HuggingFace model download + remote embed providers.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --create-home --home-dir /home/gnosis --shell /bin/false gnosis

COPY --from=builder /install /usr/local

RUN mkdir -p /data /docs \
    && chown -R gnosis:gnosis /data /home/gnosis

USER gnosis
WORKDIR /home/gnosis

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${GNOSIS_MCP_PORT}/health" || exit 1

# OCI metadata — picked up by GHCR's sidebar, docker inspect, etc.
LABEL org.opencontainers.image.title="gnosis-mcp" \
      org.opencontainers.image.description="Self-hosted MCP server for searchable documentation." \
      org.opencontainers.image.source="https://github.com/nicholasglazer/gnosis-mcp" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.documentation="https://gnosismcp.com/doc/docs/overview"

# Image entry idiom:
# - No arguments       → start the server.
# - Any argument list  → run that command (ingest, embed, check, …).
ENTRYPOINT ["gnosis-mcp"]
CMD ["serve", "--transport", "streamable-http", "--rest"]
