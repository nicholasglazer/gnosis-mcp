"""Search performance benchmark — QPS, latency percentiles, hit rate.

Usage:
    python tests/bench/bench_search.py              # default: 100 docs, 1000 queries
    python tests/bench/bench_search.py --docs 500   # custom doc count
    python tests/bench/bench_search.py --queries 5000

Requires no database — uses an in-memory SQLite backend.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from argparse import ArgumentParser

from gnosis_mcp.config import GnosisMcpConfig
from gnosis_mcp.ingest import chunk_by_headings
from gnosis_mcp.sqlite_backend import SqliteBackend

# Sample queries covering various search patterns
QUERIES = [
    "search documentation",
    "how to install",
    "configuration environment variables",
    "webhook notification",
    "PostgreSQL backend setup",
    "hybrid semantic search",
    "chunking strategy headings",
    "git commit history",
    "embedding model ONNX",
    "frontmatter metadata tags",
    "crawl sitemap depth",
    "robots.txt compliance",
    "FTS5 keyword search BM25",
    "upsert document chunks",
    "delete document path",
    "related links graph",
    "watch mode auto ingest",
    "export CSV format",
    "diff command preview",
    "streamable HTTP transport",
]


def _generate_docs(count: int) -> list[dict]:
    """Generate sample documents for benchmarking."""
    categories = ["guides", "architecture", "reference", "ops", "tutorials"]
    docs = []
    for i in range(count):
        cat = categories[i % len(categories)]
        docs.append(
            {
                "path": f"{cat}/doc-{i:04d}.md",
                "content": (
                    f"# Document {i}: {cat.title()} Topic\n\n"
                    f"This is document number {i} in the {cat} category.\n\n"
                    f"## Section A\n\n"
                    f"Content about {QUERIES[i % len(QUERIES)]} with detailed "
                    f"explanation and examples for developers.\n\n"
                    f"## Section B\n\n"
                    f"Additional context about {QUERIES[(i + 7) % len(QUERIES)]} "
                    f"including configuration options and best practices.\n\n"
                    f"## Section C\n\n"
                    f"Advanced usage patterns for {QUERIES[(i + 13) % len(QUERIES)]} "
                    f"with code examples and troubleshooting tips."
                ),
                "title": f"Document {i}",
                "category": cat,
            }
        )
    return docs


async def _run_benchmark(doc_count: int, query_count: int) -> dict:
    """Run the benchmark and return metrics."""
    cfg = GnosisMcpConfig(database_url=":memory:")
    backend = SqliteBackend(cfg)
    await backend.startup()
    await backend.init_schema()

    # Ingest docs
    docs = _generate_docs(doc_count)
    t0 = time.perf_counter()
    total_chunks = 0
    for doc in docs:
        chunks = chunk_by_headings(doc["content"], doc["path"])
        count = await backend.ingest_file(
            doc["path"],
            chunks,
            title=doc["title"],
            category=doc["category"],
            audience="all",
            tags=None,
            content_hash=None,
            has_tags_col=True,
            has_hash_col=True,
        )
        total_chunks += count
    ingest_time = time.perf_counter() - t0

    # Run queries
    latencies: list[float] = []
    hits = 0
    total_results = 0

    queries = [QUERIES[i % len(QUERIES)] for i in range(query_count)]

    t0 = time.perf_counter()
    for q in queries:
        t_start = time.perf_counter()
        results = await backend.search(q, limit=5)
        t_end = time.perf_counter()

        latencies.append((t_end - t_start) * 1000)  # ms
        if results:
            hits += 1
            total_results += len(results)
    total_time = time.perf_counter() - t0

    await backend.shutdown()

    latencies.sort()
    return {
        "docs": doc_count,
        "chunks": total_chunks,
        "ingest_time_s": round(ingest_time, 3),
        "queries": query_count,
        "total_time_s": round(total_time, 3),
        "qps": round(query_count / total_time, 1),
        "latency_p50_ms": round(statistics.median(latencies), 3),
        "latency_p95_ms": round(latencies[int(len(latencies) * 0.95)], 3),
        "latency_p99_ms": round(latencies[int(len(latencies) * 0.99)], 3),
        "latency_mean_ms": round(statistics.mean(latencies), 3),
        "hit_rate": round(hits / query_count, 3),
        "avg_results": round(total_results / max(hits, 1), 1),
    }


def main():
    parser = ArgumentParser(description="Gnosis MCP search benchmark")
    parser.add_argument("--docs", type=int, default=100, help="Number of docs to ingest")
    parser.add_argument("--queries", type=int, default=1000, help="Number of search queries")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    metrics = asyncio.run(_run_benchmark(args.docs, args.queries))

    if args.json:
        print(json.dumps(metrics, indent=2))
    else:
        print(f"\n{'=' * 55}")
        print("  Gnosis MCP Search Benchmark")
        print(f"{'=' * 55}")
        print(f"  Corpus:   {metrics['docs']} docs, {metrics['chunks']} chunks")
        print(f"  Ingest:   {metrics['ingest_time_s']}s")
        print(f"  Queries:  {metrics['queries']}")
        print(f"{'=' * 55}")
        print(f"  QPS:      {metrics['qps']}")
        print(f"  p50:      {metrics['latency_p50_ms']}ms")
        print(f"  p95:      {metrics['latency_p95_ms']}ms")
        print(f"  p99:      {metrics['latency_p99_ms']}ms")
        print(f"  Mean:     {metrics['latency_mean_ms']}ms")
        print(f"  Hit rate: {metrics['hit_rate'] * 100:.1f}%")
        print(f"  Avg results/query: {metrics['avg_results']}")
        print(f"{'=' * 55}\n")


if __name__ == "__main__":
    main()
