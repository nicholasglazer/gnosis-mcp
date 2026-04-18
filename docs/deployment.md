---
title: Deployment
category: docs
audience: all
relates_to:
  - README.md
  - docs/overview.md
  - docs/config.md
  - docs/rest-api.md
---

# Deployment

Running gnosis-mcp in production. Three common shapes:

1. **Local stdio** — one server per editor session. Default. No deployment.
2. **Shared HTTP** — one server, many clients (agent teams, CI, remote).
3. **Public REST** — expose the HTTP mirror behind a reverse proxy.

This page covers 2 and 3.

---

## Prerequisites

- Python 3.11+ (or Docker).
- A database: SQLite (zero-setup) or Postgres with pgvector (scales).
- For HTTPS deployment: a reverse proxy (Nginx, Caddy, Cloudflare Tunnel).

---

## Docker

A minimal production image. Embed provider is local ONNX; backend is
Postgres. Build your own `Dockerfile` or compose something like:

```dockerfile
FROM python:3.12-slim AS base
WORKDIR /app

RUN pip install --no-cache-dir \
    "gnosis-mcp[embeddings,postgres,web]"

ENV GNOSIS_MCP_HOST=0.0.0.0 \
    GNOSIS_MCP_PORT=8000 \
    GNOSIS_MCP_EMBED_PROVIDER=local \
    GNOSIS_MCP_ACCESS_LOG=true

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health').read()" || exit 1

CMD ["gnosis-mcp", "serve", "--transport", "streamable-http", "--rest"]
```

### docker-compose.yaml

```yaml
services:
  db:
    image: pgvector/pgvector:pg15
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: gnosis
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "postgres"]
      interval: 5s

  gnosis:
    build: .
    depends_on:
      db:
        condition: service_healthy
    environment:
      GNOSIS_MCP_DATABASE_URL: postgresql://postgres:${POSTGRES_PASSWORD}@db:5432/gnosis
      GNOSIS_MCP_API_KEY: ${GNOSIS_MCP_API_KEY}
      GNOSIS_MCP_WRITABLE: "true"
    ports: ["127.0.0.1:8000:8000"]
    restart: unless-stopped

volumes:
  pgdata:
```

**First boot:**

```bash
docker compose up -d db
docker compose run --rm gnosis gnosis-mcp init-db
docker compose run --rm -v $PWD/docs:/mnt/docs gnosis \
  gnosis-mcp ingest /mnt/docs --embed
docker compose up -d gnosis
```

### Mounting the SQLite DB (SQLite-only deployments)

```yaml
services:
  gnosis:
    image: ghcr.io/nicholasglazer/gnosis-mcp:latest
    volumes:
      - gnosis-data:/root/.local/share/gnosis-mcp
      - ./docs:/mnt/docs:ro
    environment:
      GNOSIS_MCP_EMBED_PROVIDER: local
    command: >
      gnosis-mcp serve --transport streamable-http --rest
      --watch /mnt/docs
volumes:
  gnosis-data:
```

---

## systemd

For bare-metal servers without Docker.

`/etc/systemd/system/gnosis-mcp.service`:

```ini
[Unit]
Description=gnosis-mcp documentation server
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=exec
User=gnosis
Group=gnosis
WorkingDirectory=/var/lib/gnosis-mcp
EnvironmentFile=/etc/gnosis-mcp/env
ExecStart=/usr/bin/gnosis-mcp serve --transport streamable-http --rest
Restart=on-failure
RestartSec=5
RuntimeMaxSec=1w
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/gnosis-mcp

[Install]
WantedBy=multi-user.target
```

`/etc/gnosis-mcp/env` (mode 0600, owned by gnosis):

```env
GNOSIS_MCP_DATABASE_URL=postgresql://gnosis:REDACTED@localhost:5432/gnosis
GNOSIS_MCP_API_KEY=REDACTED
GNOSIS_MCP_HOST=127.0.0.1
GNOSIS_MCP_PORT=8000
GNOSIS_MCP_EMBED_PROVIDER=local
GNOSIS_MCP_WRITABLE=true
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now gnosis-mcp
sudo systemctl status gnosis-mcp
journalctl -u gnosis-mcp -f
```

---

## Reverse proxy

### Nginx

```nginx
upstream gnosis {
  server 127.0.0.1:8000;
  keepalive 8;
}

server {
  listen 443 ssl http2;
  server_name docs.example.com;

  # … your TLS config …

  location /health {
    proxy_pass http://gnosis;
  }

  # MCP streamable-http endpoint (long-lived)
  location /mcp {
    proxy_pass http://gnosis;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_read_timeout 3600;  # long-lived streams
    proxy_buffering off;
  }

  # REST endpoints
  location /api/ {
    proxy_pass http://gnosis;
    proxy_http_version 1.1;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
}
```

### Caddy

```caddyfile
docs.example.com {
  reverse_proxy 127.0.0.1:8000 {
    transport http {
      keepalive 30s
      response_header_timeout 1h  # for /mcp
    }
  }
}
```

### Cloudflare Tunnel (zero-config TLS)

```bash
cloudflared tunnel create gnosis
cloudflared tunnel route dns gnosis docs.example.com
cloudflared tunnel --url http://127.0.0.1:8000 run gnosis
```

Or write a proper `~/.cloudflared/config.yml` and run as a systemd unit.

---

## Security checklist

- [ ] **Bind loopback** unless you have a reverse proxy:
  `GNOSIS_MCP_HOST=127.0.0.1`.
- [ ] **Set `GNOSIS_MCP_API_KEY`** for any non-loopback exposure. 32+ random
  bytes: `python -c 'import secrets; print(secrets.token_urlsafe(32))'`.
- [ ] **`GNOSIS_MCP_WRITABLE=false`** unless clients need it (defaults to
  false).
- [ ] **CORS** — don't set `GNOSIS_MCP_CORS_ORIGINS=*` on production;
  list the exact origins you trust.
- [ ] **Restrict webhook targets** — keep `GNOSIS_MCP_WEBHOOK_ALLOW_PRIVATE`
  at `false` unless you need loopback callbacks.
- [ ] **Put a reverse proxy in front** for TLS; the server itself is plain
  HTTP by design (so any TLS story works).
- [ ] **Rate-limit at the proxy**, not the app. We don't ship a rate
  limiter because Nginx / Cloudflare do a better job.
- [ ] **Rotate `GNOSIS_MCP_API_KEY` periodically** — systemd
  `EnvironmentFile` makes this a single-file change + restart.
- [ ] **Pin a specific image tag** in prod. `latest` bites you on upgrade
  day.

---

## Observability

The server logs to stdout with structured lines. Forward with your usual
stack (journald → Loki, Docker logs → Datadog, etc.).

Health: `GET /health` returns JSON with `status`, `version`, `docs`,
`chunks`, `backend`. Use it for:

- Kubernetes readiness / liveness probes.
- Cloudflare / Uptime-Robot / Healthchecks.io pings.
- Alerting pipelines — probe every 60 s, alert if `status != "ok"` or
  response time > 1 s.

Access log is stored in the database (`search_access_log` table) and
feeds the `get_context` tool. Prune with
`gnosis-mcp cleanup --days 30` on a weekly cron.

### Metrics

gnosis-mcp does not ship a `/metrics` Prometheus endpoint in 0.10.x. Planned
for post-1.0. If you need metrics now, scrape `/health` for doc count
trends and instrument your reverse proxy for HTTP metrics.

---

## Upgrading

```bash
pip install --upgrade gnosis-mcp
gnosis-mcp init-db      # idempotent — creates any new tables/indexes
gnosis-mcp check        # sanity
systemctl restart gnosis-mcp
```

Minor-version bumps may add schema. `init-db` is always safe to re-run.

For pre-0.10 upgrades, run `gnosis-mcp fix-link-types` once to migrate
git-history link types to the new taxonomy.

---

## See also

- [Configuration reference](config.md) — every env var.
- [REST API reference](rest-api.md) — what endpoints you're proxying.
- [Troubleshooting](troubleshooting.md) — when it breaks.
