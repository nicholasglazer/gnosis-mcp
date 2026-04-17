# Contributing to gnosis-mcp

Thanks for your interest in contributing. This is a Python MCP server for searchable documentation, and issues / PRs are welcome.

## Getting Started

You need Python 3.11+ and [`uv`](https://github.com/astral-sh/uv) (recommended) or `pip`.

```bash
git clone https://github.com/nicholasglazer/gnosis-mcp.git
cd gnosis-mcp
uv sync --extra dev --extra embeddings --extra postgres --extra web --extra rst --extra pdf
```

Run the test suite:

```bash
uv run pytest          # fast: SQLite only
uv run pytest -m "not e2e"   # skip end-to-end MCP protocol tests
```

Lint and format:

```bash
uv run ruff check .
uv run ruff format --check .
```

## PR Process

1. Fork, create a branch (`fix/<short-desc>` or `feat/<short-desc>`).
2. Write or update tests. We expect genuine assertions — not smoke tests.
3. Run `uv run pytest` locally until green.
4. Run `uv run ruff check . && uv run ruff format --check .` — CI will gate on this.
5. Open a PR. CI runs pytest + ruff on SQLite and PostgreSQL. Address review comments; we aim for a same-week turnaround for small PRs.

## Commit Style

Prefix commits with `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`, or `ci:`. Reference issue numbers in the body (not the title). Keep the subject under 72 chars.

## Testing Against PostgreSQL

Most contributors only need SQLite. If your change touches `pg_backend.py` or uses Postgres-specific SQL, run:

```bash
docker run -d --name gnosis-pg -e POSTGRES_PASSWORD=pw -p 5432:5432 pgvector/pgvector:pg15
psql postgresql://postgres:pw@localhost/postgres -c "CREATE EXTENSION IF NOT EXISTS vector;"
GNOSIS_MCP_CI_PG=1 \
GNOSIS_MCP_DATABASE_URL=postgresql://postgres:pw@localhost/postgres \
uv run pytest
```

## Release Process (maintainers only)

See the **Releases** section of `CLAUDE.md`. Four files must bump in lockstep:

- `pyproject.toml`
- `src/gnosis_mcp/__init__.py`
- `server.json`
- `marketplace.json`

Run `bash scripts/check-versions.sh` to verify parity before tagging.

PyPI + MCP Registry publishing is automated via `.github/workflows/publish.yml` on `v*` tag push or `pyproject.toml` version change on `main`.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Report unacceptable behavior to info@nicgl.com.

## Reporting Security Issues

Do **not** open a public issue for vulnerabilities. See [`SECURITY.md`](SECURITY.md).

## License

By contributing, you agree your contributions will be licensed under the MIT License (see `LICENSE`).
