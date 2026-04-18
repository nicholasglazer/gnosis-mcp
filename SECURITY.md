# Security Policy

## Supported Versions

The latest 0.11.x patch receives security fixes. Older versions are unsupported.

## Reporting a Vulnerability

Please do **not** open a public issue.

1. Report privately via [GitHub Security Advisories](https://github.com/nicholasglazer/gnosis-mcp/security/advisories/new) (preferred).
2. Or email info@nicgl.com with details and a reproduction.

## Response Time

- **Acknowledgement:** within 48 hours
- **Initial triage:** within 7 days
- **Coordinated disclosure:** we'll agree on a fix window and public disclosure date with you

## Scope

In scope: the library source, published PyPI artefacts, publish workflow, MCP tools/resources surface.

Out of scope: user-authored documents ingested by the server, third-party MCP clients, user deployment configurations (network exposure, reverse proxies, etc.).

## Hardening Notes

- REST API authentication uses `secrets.compare_digest` for timing-safe comparison.
- Webhook URLs (`GNOSIS_MCP_WEBHOOK_URL`) are validated — private, loopback, link-local, and multicast addresses are refused unless `GNOSIS_MCP_WEBHOOK_ALLOW_PRIVATE=true`.
- Model downloads verify TLS origin (`huggingface.co`) and SHA-256 checksums for the bundled default model.
- Web crawl enforces same-host robots.txt (redirects across hosts are treated as disallow).
- Input size caps are enforced (50 MB per document, 10 KB per search query).
- SQL identifiers are regex-validated at config load; all queries use parameterised bindings.
