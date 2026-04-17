"""End-to-end MCP protocol latency benchmark.

Measures what a real MCP client (like Claude Code) pays per tool call,
not just in-process search latency. Spawns `gnosis-mcp serve --transport stdio`
as a subprocess and times N round-trips through the MCP wire protocol.

Usage:
    uv run python tests/bench/bench_mcp_e2e.py
    uv run python tests/bench/bench_mcp_e2e.py --json --queries 200
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import tempfile
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def _run(queries: int, use_json: bool) -> None:
    import subprocess

    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "e2e.db")
        env = os.environ.copy()
        env["GNOSIS_MCP_DATABASE_URL"] = f"sqlite:///{db}"
        env["GNOSIS_MCP_WRITABLE"] = "true"
        env["GNOSIS_MCP_BACKEND"] = "sqlite"
        env["GNOSIS_MCP_LOG_LEVEL"] = "WARNING"

        # Pre-initialize schema so the first search doesn't race
        subprocess.run(
            [sys.executable, "-m", "gnosis_mcp", "init-db"],
            env=env,
            check=True,
            capture_output=True,
            timeout=30,
        )

        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "gnosis_mcp", "serve", "--transport", "stdio"],
            env=env,
        )

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                t = time.perf_counter()
                await session.initialize()
                init_ms = (time.perf_counter() - t) * 1000

                t = time.perf_counter()
                await session.list_tools()
                list_tools_ms = (time.perf_counter() - t) * 1000

                # Seed a document so search returns something
                await session.call_tool(
                    "upsert_doc",
                    {
                        "path": "bench.md",
                        "content": "# Bench\n\nQuick brown fox. Authentication setup. PostgreSQL config.\n",
                        "title": "Bench",
                        "category": "bench",
                    },
                )

                latencies: list[float] = []
                for i in range(queries):
                    t = time.perf_counter()
                    await session.call_tool("search_docs", {"query": "authentication", "limit": 5})
                    latencies.append((time.perf_counter() - t) * 1000)

    def pct(p: float) -> float:
        s = sorted(latencies)
        return s[min(len(s) - 1, int(len(s) * p / 100))]

    results = {
        "queries": queries,
        "init_ms": round(init_ms, 3),
        "list_tools_ms": round(list_tools_ms, 3),
        "search_docs": {
            "p50_ms": round(pct(50), 3),
            "p95_ms": round(pct(95), 3),
            "p99_ms": round(pct(99), 3),
            "mean_ms": round(statistics.mean(latencies), 3),
            "min_ms": round(min(latencies), 3),
        },
    }
    if use_json:
        print(json.dumps(results, indent=2))
        return

    print(f"\nMCP E2E Protocol Benchmark — {queries} search_docs round-trips")
    print("=" * 60)
    print(f"  initialize:    {results['init_ms']:>8.2f} ms  (one-time handshake)")
    print(f"  list_tools:    {results['list_tools_ms']:>8.2f} ms")
    print("  search_docs:")
    print(f"    mean:        {results['search_docs']['mean_ms']:>8.2f} ms")
    print(f"    p50:         {results['search_docs']['p50_ms']:>8.2f} ms")
    print(f"    p95:         {results['search_docs']['p95_ms']:>8.2f} ms")
    print(f"    p99:         {results['search_docs']['p99_ms']:>8.2f} ms")
    print(f"    min:         {results['search_docs']['min_ms']:>8.2f} ms")
    print("=" * 60)


def main() -> None:
    ap = argparse.ArgumentParser(description="End-to-end MCP protocol latency bench")
    ap.add_argument("--queries", type=int, default=100)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    asyncio.run(_run(args.queries, args.json))


if __name__ == "__main__":
    main()
