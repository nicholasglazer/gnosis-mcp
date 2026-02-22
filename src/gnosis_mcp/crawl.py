"""Web crawl for documentation sites: discover URLs, fetch pages, extract content, ingest.

Supports sitemap.xml discovery, BFS link crawling, robots.txt compliance,
ETag/Last-Modified caching, and rate-limited concurrent fetching.

Requires the [web] extra: pip install gnosis-mcp[web]
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

from gnosis_mcp import __version__
from gnosis_mcp.ingest import chunk_by_headings, content_hash

if TYPE_CHECKING:
    import httpx

    from gnosis_mcp.backend import DocBackend
    from gnosis_mcp.config import GnosisMcpConfig

__all__ = [
    "CrawlAction",
    "CrawlResult",
    "CrawlConfig",
    "normalize_url",
    "parse_sitemap",
    "check_robots",
    "extract_links",
    "url_matches_pattern",
    "load_cache",
    "save_cache",
    "crawl_url",
]

log = logging.getLogger("gnosis_mcp")

_CACHE_DIR = Path.home() / ".local" / "share" / "gnosis-mcp"
_CACHE_FILE = _CACHE_DIR / "crawl-cache.json"
_MAX_XML_SIZE = 10 * 1024 * 1024  # 10 MB — reject oversized sitemaps
_MAX_RESPONSE_SIZE = 50 * 1024 * 1024  # 50 MB — reject oversized HTML responses
_MAX_DEPTH = 10  # Hard cap on BFS crawl depth


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class CrawlAction(StrEnum):
    """Actions that can occur when processing a URL."""

    CRAWLED = "crawled"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"
    ERROR = "error"
    BLOCKED = "blocked"
    DRY_RUN = "dry-run"


@dataclass
class CrawlResult:
    """Result of crawling a single URL."""

    url: str
    chunks: int
    action: CrawlAction
    detail: str = ""


@dataclass(frozen=True)
class CrawlConfig:
    """Configuration for a crawl session."""

    sitemap: bool = False
    depth: int = 1
    include: str | None = None
    exclude: str | None = None
    concurrency: int = 5
    delay: float = 0.2
    user_agent: str = field(default_factory=lambda: f"gnosis-mcp/{__version__}")
    timeout: float = 30.0
    dry_run: bool = False
    force: bool = False
    embed: bool = False
    max_urls: int = 5000

    def __post_init__(self) -> None:
        if self.depth > _MAX_DEPTH:
            object.__setattr__(self, "depth", _MAX_DEPTH)


@dataclass
class _FetchResult:
    """Internal result from fetch_page."""

    url: str
    html: str
    etag: str | None = None
    last_modified: str | None = None


# ---------------------------------------------------------------------------
# Pure functions (testable without network/DB)
# ---------------------------------------------------------------------------


def _is_private_host(hostname: str) -> bool:
    """Return True if hostname is a private/internal address (SSRF protection)."""
    lower = hostname.lower().split(":")[0]  # strip port
    if lower in ("localhost", "localhost.localdomain", ""):
        return True
    if lower.endswith((".local", ".internal")):
        return True
    try:
        addr = ipaddress.ip_address(lower)
        return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
    except ValueError:
        return False


def normalize_url(url: str) -> str:
    """Canonical form: lowercase scheme+host, strip fragment, strip trailing slash on path."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/") if parsed.path != "/" else "/"
    # Rebuild without fragment, keep query
    return urlunparse((scheme, host, path, parsed.params, parsed.query, ""))


def parse_sitemap(xml_text: str) -> list[str]:
    """Extract <loc> URLs from sitemap XML (handles namespace)."""
    if len(xml_text) > _MAX_XML_SIZE:
        log.warning("Sitemap exceeds %d bytes, skipping", _MAX_XML_SIZE)
        return []

    urls: list[str] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return urls

    # Handle namespace: {http://www.sitemaps.org/schemas/sitemap/0.9}
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    # Sitemap index: <sitemap><loc>...</loc></sitemap>
    for sitemap_el in root.findall(f".//{ns}sitemap"):
        loc = sitemap_el.find(f"{ns}loc")
        if loc is not None and loc.text:
            urls.append(loc.text.strip())

    # Regular sitemap: <url><loc>...</loc></url>
    for url_el in root.findall(f".//{ns}url"):
        loc = url_el.find(f"{ns}loc")
        if loc is not None and loc.text:
            urls.append(loc.text.strip())

    return urls


def check_robots(robots_txt: str, url: str, user_agent: str) -> bool:
    """Return True if the URL is allowed by robots.txt."""
    rp = RobotFileParser()
    rp.parse(robots_txt.splitlines())
    return rp.can_fetch(user_agent, url)


def _parse_robots(robots_txt: str) -> RobotFileParser:
    """Parse robots.txt once into a reusable RobotFileParser."""
    rp = RobotFileParser()
    rp.parse(robots_txt.splitlines())
    return rp


_HREF_RE = re.compile(r'<a\s[^>]*href=["\']([^"\']+)["\']', re.IGNORECASE)


def extract_links(html: str, base_url: str, same_host_only: bool = True) -> list[str]:
    """Extract unique internal links from HTML."""
    parsed_base = urlparse(base_url)
    base_host = parsed_base.netloc.lower()
    seen: set[str] = set()
    result: list[str] = []

    for match in _HREF_RE.finditer(html):
        href = match.group(1).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        if same_host_only and parsed.netloc.lower() != base_host:
            continue
        normalized = normalize_url(absolute)
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)

    return result


def url_matches_pattern(url: str, pattern: str) -> bool:
    """Match URL path against a glob pattern using fnmatch."""
    path = urlparse(url).path
    return fnmatch(path, pattern)


def load_cache(path: Path | None = None) -> dict:
    """Load crawl cache from JSON file."""
    cache_path = path or _CACHE_FILE
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_cache(data: dict, path: Path | None = None) -> None:
    """Save crawl cache atomically to JSON file with restricted permissions."""
    cache_path = path or _CACHE_FILE
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: temp file + os.replace prevents corruption on crash
    fd, tmp_path = tempfile.mkstemp(dir=cache_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, cache_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Async functions
# ---------------------------------------------------------------------------


def _require_httpx():
    """Deferred import for httpx — raises ImportError with install instructions."""
    try:
        import httpx
        return httpx
    except ImportError:
        raise ImportError(
            "Web crawling requires the [web] extra.\n"
            "Install with: pip install gnosis-mcp[web]"
        ) from None


def _require_trafilatura():
    """Deferred import for trafilatura — raises ImportError with install instructions."""
    try:
        import trafilatura
        return trafilatura
    except ImportError:
        raise ImportError(
            "Web crawling requires the [web] extra.\n"
            "Install with: pip install gnosis-mcp[web]"
        ) from None


async def fetch_page(
    client: httpx.AsyncClient,
    url: str,
    cache: dict,
    force: bool = False,
) -> _FetchResult | None:
    """GET a URL with conditional requests. Returns None on 304 Not Modified."""
    headers: dict[str, str] = {}
    cached = cache.get(url)
    if cached and not force:
        if cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]
        if cached.get("last_modified"):
            headers["If-Modified-Since"] = cached["last_modified"]

    response = await client.get(url, headers=headers, follow_redirects=True)

    if response.status_code == 304:
        return None
    response.raise_for_status()

    # SSRF: check final URL after redirects
    final_host = urlparse(str(response.url)).hostname or ""
    if _is_private_host(final_host):
        log.warning("Blocked redirect to private host: %s", final_host)
        return None

    # Response size guard
    content_length = response.headers.get("content-length")
    if content_length and int(content_length) > _MAX_RESPONSE_SIZE:
        log.warning("Response too large (%s bytes): %s", content_length, url)
        return None

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        return None

    return _FetchResult(
        url=str(response.url),
        html=response.text,
        etag=response.headers.get("etag"),
        last_modified=response.headers.get("last-modified"),
    )


async def extract_content(html: str, url: str) -> str | None:
    """Extract main content from HTML as markdown using trafilatura.

    Runs in a thread pool because trafilatura.extract() is CPU-bound
    (HTML parsing + content extraction) and would block the event loop.
    """
    trafilatura = _require_trafilatura()
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: trafilatura.extract(
            html,
            url=url,
            output_format="markdown",
            include_links=True,
            include_tables=True,
            include_images=False,
            favor_precision=True,
        ),
    )
    return result if result and len(result.strip()) >= 50 else None


async def discover_urls(
    client: httpx.AsyncClient,
    base_url: str,
    config: CrawlConfig,
    robots_txt: str | None = None,
) -> list[str]:
    """Discover URLs via sitemap.xml or BFS link crawl."""
    parsed = urlparse(base_url)
    base_host = parsed.netloc.lower()
    robots = _parse_robots(robots_txt) if robots_txt else None

    if config.sitemap:
        return await _discover_sitemap(client, base_url, base_host, robots, config)

    return await _discover_bfs(client, base_url, config, robots)


async def _discover_sitemap(
    client: httpx.AsyncClient,
    base_url: str,
    base_host: str,
    robots: RobotFileParser | None,
    config: CrawlConfig,
) -> list[str]:
    """Discover URLs from sitemap.xml (handles sitemap index)."""
    parsed = urlparse(base_url)
    sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"

    try:
        resp = await client.get(sitemap_url, follow_redirects=True)
        resp.raise_for_status()
    except Exception:
        log.warning("Could not fetch sitemap at %s, falling back to BFS", sitemap_url)
        return await _discover_bfs(client, base_url, config, robots)

    urls = parse_sitemap(resp.text)

    # Handle sitemap index — resolve nested sitemaps in parallel
    nested_sitemaps = [u for u in urls if u.endswith(".xml") or "sitemap" in u.lower()]
    if nested_sitemaps and len(nested_sitemaps) == len(urls):

        async def _fetch_nested(sm_url: str) -> list[str]:
            try:
                sm_resp = await client.get(sm_url, follow_redirects=True)
                sm_resp.raise_for_status()
                return parse_sitemap(sm_resp.text)
            except Exception:
                log.warning("Could not fetch nested sitemap: %s", sm_url)
                return []

        nested_results = await asyncio.gather(
            *[_fetch_nested(sm) for sm in nested_sitemaps]
        )
        urls = [u for batch in nested_results for u in batch]

    # Filter to same host and normalize
    result = []
    for u in urls:
        parsed_u = urlparse(u)
        if parsed_u.netloc.lower() == base_host:
            result.append(normalize_url(u))
    return result


async def _discover_bfs(
    client: httpx.AsyncClient,
    base_url: str,
    config: CrawlConfig,
    robots: RobotFileParser | None,
) -> list[str]:
    """BFS link crawl with depth limit."""
    base_normalized = normalize_url(base_url)
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(base_normalized, 0)])
    result: list[str] = []

    while queue and len(result) < config.max_urls:
        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        if robots is not None and not robots.can_fetch(config.user_agent, url):
            continue

        result.append(url)

        if depth >= config.depth:
            continue

        try:
            resp = await client.get(url, follow_redirects=True)
            ct = resp.headers.get("content-type", "")
            if resp.status_code == 200 and "text/html" in ct:
                links = extract_links(resp.text, url, same_host_only=True)
                for link in links:
                    if link not in visited and len(queue) < config.max_urls:
                        queue.append((link, depth + 1))
        except Exception:
            continue

        if config.delay > 0:
            await asyncio.sleep(config.delay)

    return result


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


async def crawl_url(
    gnosis_config: GnosisMcpConfig,
    url: str,
    crawl_config: CrawlConfig,
    cache_path: Path | None = None,
) -> list[CrawlResult]:
    """Main crawl orchestrator: discover, fetch, extract, ingest.

    Args:
        gnosis_config: GnosisMcpConfig instance.
        url: Base URL to crawl.
        crawl_config: CrawlConfig with crawl options.
        cache_path: Override cache file path (for testing).

    Returns:
        List of CrawlResult for each URL processed.
    """
    httpx = _require_httpx()

    # SSRF: block private base URLs
    base_host = urlparse(url).hostname or ""
    if _is_private_host(base_host):
        return [CrawlResult(
            url=url, chunks=0, action=CrawlAction.BLOCKED,
            detail="private/internal host blocked",
        )]

    # 1. Load crawl cache
    cache = load_cache(cache_path)

    results: list[CrawlResult] = []
    parsed = urlparse(url)
    category = parsed.netloc.lower()

    async with httpx.AsyncClient(
        timeout=crawl_config.timeout,
        headers={"User-Agent": crawl_config.user_agent},
    ) as client:
        # 2. Fetch robots.txt (parse once, reuse for all URLs)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        robots_txt: str | None = None
        robots: RobotFileParser | None = None
        try:
            robots_resp = await client.get(robots_url, follow_redirects=True)
            if robots_resp.status_code == 200:
                robots_txt = robots_resp.text
                robots = _parse_robots(robots_txt)
        except Exception:
            log.debug("Could not fetch robots.txt from %s", robots_url)

        # 3. Discover URLs
        discovered = await discover_urls(client, url, crawl_config, robots_txt)
        log.info("Discovered %d URL(s) from %s", len(discovered), url)

        # 4. Apply include/exclude filters
        if crawl_config.include:
            discovered = [u for u in discovered if url_matches_pattern(u, crawl_config.include)]
        if crawl_config.exclude:
            discovered = [u for u in discovered if not url_matches_pattern(u, crawl_config.exclude)]

        # 4b. Cap URL count to prevent runaway memory usage
        if len(discovered) > crawl_config.max_urls:
            log.warning(
                "Truncating %d discovered URLs to --max-urls %d",
                len(discovered), crawl_config.max_urls,
            )
            discovered = discovered[:crawl_config.max_urls]

        # 5. Dry run — return early
        if crawl_config.dry_run:
            for u in discovered:
                results.append(CrawlResult(url=u, chunks=0, action=CrawlAction.DRY_RUN))
            return results

        # 6. Setup backend
        from gnosis_mcp.backend import create_backend

        backend = create_backend(gnosis_config)
        await backend.startup()

        try:
            # Auto-init schema
            table_name = gnosis_config.chunks_tables[0]
            table_exists = await backend.has_column(table_name, "file_path")
            if not table_exists:
                await backend.init_schema()

            has_hash = await backend.has_column(table_name, "content_hash")
            has_tags = await backend.has_column(table_name, "tags")

            # 7. Crawl with concurrency control
            sem = asyncio.Semaphore(crawl_config.concurrency)

            async def _process_url(target_url: str) -> CrawlResult:
                async with sem:
                    return await _crawl_single(
                        client=client,
                        backend=backend,
                        url=target_url,
                        cache=cache,
                        config=crawl_config,
                        category=category,
                        has_hash=has_hash,
                        has_tags=has_tags,
                        robots=robots,
                    )

            tasks = [_process_url(u) for u in discovered]
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Convert exceptions to error results
            results = []
            for i, r in enumerate(raw_results):
                if isinstance(r, BaseException):
                    results.append(CrawlResult(
                        url=discovered[i], chunks=0,
                        action=CrawlAction.ERROR, detail=str(r),
                    ))
                else:
                    results.append(r)

            # 8. Embed if requested
            if crawl_config.embed:
                crawled_count = sum(1 for r in results if r.action == CrawlAction.CRAWLED)
                if crawled_count > 0:
                    try:
                        from gnosis_mcp.embed import embed_pending

                        provider = gnosis_config.embed_provider
                        if not provider:
                            try:
                                import onnxruntime  # noqa: F401
                                import tokenizers  # noqa: F401
                                provider = "local"
                            except ImportError:
                                pass

                        if provider:
                            model = (
                                gnosis_config.embed_model
                                if gnosis_config.embed_provider
                                else "MongoDB/mdbr-leaf-ir"
                            )
                            log.info("Embedding crawled chunks (provider=%s)...", provider)
                            await embed_pending(
                                config=gnosis_config,
                                provider=provider,
                                model=model,
                                api_key=gnosis_config.embed_api_key,
                                url=gnosis_config.embed_url,
                                batch_size=gnosis_config.embed_batch_size,
                                dim=gnosis_config.embed_dim,
                            )
                        else:
                            log.warning("Skipping --embed: no provider configured")
                    except ImportError:
                        log.warning("Skipping --embed: embedding dependencies not installed")

        finally:
            # Always save cache, even on error/cancellation
            save_cache(cache, cache_path)
            await backend.shutdown()

    return results


async def _crawl_single(
    *,
    client: httpx.AsyncClient,
    backend: DocBackend,
    url: str,
    cache: dict,
    config: CrawlConfig,
    category: str,
    has_hash: bool,
    has_tags: bool,
    robots: RobotFileParser | None,
) -> CrawlResult:
    """Crawl a single URL: fetch, extract, chunk, ingest."""
    # Check robots.txt (uses pre-parsed RobotFileParser — parsed once, not per URL)
    if robots is not None and not robots.can_fetch(config.user_agent, url):
        return CrawlResult(url=url, chunks=0, action=CrawlAction.BLOCKED, detail="robots.txt")

    try:
        # Fetch with conditional request
        fetch_result = await fetch_page(client, url, cache, force=config.force)
        if fetch_result is None:
            return CrawlResult(
                url=url, chunks=0, action=CrawlAction.UNCHANGED, detail="304 Not Modified",
            )

        # Extract content
        markdown = await extract_content(fetch_result.html, url)
        if markdown is None:
            return CrawlResult(
                url=url, chunks=0, action=CrawlAction.SKIPPED, detail="No extractable content",
            )

        # Content hash check
        digest = content_hash(markdown)
        if has_hash and not config.force:
            existing = await backend.get_content_hash(url)
            if existing == digest:
                # Update cache entry even if content unchanged
                cache[url] = {
                    "etag": fetch_result.etag,
                    "last_modified": fetch_result.last_modified,
                    "hash": digest,
                    "timestamp": time.time(),
                }
                return CrawlResult(
                    url=url, chunks=0, action=CrawlAction.UNCHANGED, detail="hash match",
                )

        # Chunk
        chunks = chunk_by_headings(markdown, url)

        # Extract title from first chunk or URL path
        title = chunks[0]["title"] if chunks else urlparse(url).path.strip("/").split("/")[-1]

        # Ingest
        count = await backend.ingest_file(
            url,
            chunks,
            title=title,
            category=category,
            audience="all",
            content_hash=digest,
            has_tags_col=has_tags,
            has_hash_col=has_hash,
        )

        # Extract and insert internal links for the doc graph
        links = extract_links(fetch_result.html, url, same_host_only=True)
        if links:
            try:
                await backend.insert_links(url, links[:50], relation_type="links_to")
            except Exception:
                log.debug("insert_links failed for %s (links table may not exist)", url)

        # Update cache
        cache[url] = {
            "etag": fetch_result.etag,
            "last_modified": fetch_result.last_modified,
            "hash": digest,
            "timestamp": time.time(),
        }

        # Rate limiting
        if config.delay > 0:
            await asyncio.sleep(config.delay)

        return CrawlResult(url=url, chunks=count, action=CrawlAction.CRAWLED)

    except asyncio.CancelledError:
        raise  # Never swallow cancellation
    except Exception as e:
        return CrawlResult(url=url, chunks=0, action=CrawlAction.ERROR, detail=str(e))
