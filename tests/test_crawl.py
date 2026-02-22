"""Tests for gnosis_mcp.crawl — URL normalization, sitemap parsing, robots.txt,
link extraction, URL pattern matching, cache I/O, crawl orchestration, and security."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import stat
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gnosis_mcp.crawl import (
    CrawlAction,
    CrawlConfig,
    CrawlResult,
    _is_private_host,
    _MAX_DEPTH,
    _MAX_XML_SIZE,
    _parse_robots,
    check_robots,
    extract_links,
    load_cache,
    normalize_url,
    parse_sitemap,
    save_cache,
    url_matches_pattern,
)


def _has_httpx() -> bool:
    return importlib.util.find_spec("httpx") is not None


# ===========================================================================
# CrawlAction StrEnum
# ===========================================================================


class TestCrawlAction:
    def test_values(self):
        assert CrawlAction.CRAWLED == "crawled"
        assert CrawlAction.UNCHANGED == "unchanged"
        assert CrawlAction.SKIPPED == "skipped"
        assert CrawlAction.ERROR == "error"
        assert CrawlAction.BLOCKED == "blocked"
        assert CrawlAction.DRY_RUN == "dry-run"

    def test_is_str_subclass(self):
        assert isinstance(CrawlAction.CRAWLED, str)

    def test_string_comparison(self):
        assert CrawlAction.CRAWLED == "crawled"
        assert "crawled" == CrawlAction.CRAWLED


# ===========================================================================
# _is_private_host (SSRF protection)
# ===========================================================================


class TestIsPrivateHost:
    def test_localhost(self):
        assert _is_private_host("localhost") is True

    def test_localhost_localdomain(self):
        assert _is_private_host("localhost.localdomain") is True

    def test_empty_string(self):
        assert _is_private_host("") is True

    def test_loopback_ipv4(self):
        assert _is_private_host("127.0.0.1") is True

    def test_loopback_ipv6(self):
        assert _is_private_host("::1") is True

    def test_private_10(self):
        assert _is_private_host("10.0.0.1") is True

    def test_private_172(self):
        assert _is_private_host("172.16.0.1") is True

    def test_private_192(self):
        assert _is_private_host("192.168.1.1") is True

    def test_link_local(self):
        assert _is_private_host("169.254.1.1") is True

    def test_dot_local(self):
        assert _is_private_host("myservice.local") is True

    def test_dot_internal(self):
        assert _is_private_host("api.internal") is True

    def test_public_ip(self):
        assert _is_private_host("8.8.8.8") is False

    def test_public_domain(self):
        assert _is_private_host("docs.stripe.com") is False

    def test_strips_port(self):
        assert _is_private_host("127.0.0.1:8080") is True

    def test_case_insensitive(self):
        assert _is_private_host("LOCALHOST") is True

    def test_metadata_ip(self):
        # AWS metadata endpoint
        assert _is_private_host("169.254.169.254") is True


# ===========================================================================
# normalize_url
# ===========================================================================


class TestNormalizeUrl:
    def test_strips_fragment(self):
        assert normalize_url("https://example.com/page#section") == "https://example.com/page"

    def test_strips_trailing_slash(self):
        assert normalize_url("https://example.com/docs/") == "https://example.com/docs"

    def test_preserves_root_slash(self):
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_lowercases_scheme(self):
        assert normalize_url("HTTPS://Example.COM/Path") == "https://example.com/Path"

    def test_lowercases_host(self):
        assert normalize_url("https://DOCS.Example.COM/api") == "https://docs.example.com/api"

    def test_preserves_query(self):
        assert normalize_url("https://example.com/search?q=test") == "https://example.com/search?q=test"

    def test_preserves_path_case(self):
        # Path case is significant (unlike host)
        assert normalize_url("https://example.com/API/Charges") == "https://example.com/API/Charges"

    def test_empty_path(self):
        result = normalize_url("https://example.com")
        assert "example.com" in result

    def test_complex_url(self):
        url = "https://docs.stripe.com/api/charges?expand=true#create"
        result = normalize_url(url)
        assert result == "https://docs.stripe.com/api/charges?expand=true"

    def test_http_scheme(self):
        assert normalize_url("http://example.com/page") == "http://example.com/page"

    def test_port_preserved(self):
        assert normalize_url("https://example.com:8080/page") == "https://example.com:8080/page"

    def test_double_trailing_slash(self):
        result = normalize_url("https://example.com/docs//")
        assert not result.endswith("//")

    def test_idempotent(self):
        url = "https://docs.example.com/api/v2"
        assert normalize_url(normalize_url(url)) == normalize_url(url)


# ===========================================================================
# parse_sitemap
# ===========================================================================


class TestParseSitemap:
    def test_basic_sitemap(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.com/page1</loc></url>
          <url><loc>https://example.com/page2</loc></url>
        </urlset>"""
        urls = parse_sitemap(xml)
        assert urls == ["https://example.com/page1", "https://example.com/page2"]

    def test_sitemap_without_namespace(self):
        xml = """<?xml version="1.0"?>
        <urlset>
          <url><loc>https://example.com/a</loc></url>
        </urlset>"""
        urls = parse_sitemap(xml)
        assert urls == ["https://example.com/a"]

    def test_sitemap_index(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>https://example.com/sitemap-posts.xml</loc></sitemap>
          <sitemap><loc>https://example.com/sitemap-pages.xml</loc></sitemap>
        </sitemapindex>"""
        urls = parse_sitemap(xml)
        assert len(urls) == 2
        assert "https://example.com/sitemap-posts.xml" in urls

    def test_empty_sitemap(self):
        xml = """<?xml version="1.0"?><urlset></urlset>"""
        assert parse_sitemap(xml) == []

    def test_invalid_xml(self):
        assert parse_sitemap("not xml at all") == []

    def test_whitespace_in_loc(self):
        xml = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>  https://example.com/page  </loc></url>
        </urlset>"""
        urls = parse_sitemap(xml)
        assert urls == ["https://example.com/page"]

    def test_missing_loc(self):
        xml = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><lastmod>2024-01-01</lastmod></url>
        </urlset>"""
        assert parse_sitemap(xml) == []

    def test_mixed_sitemap_with_lastmod(self):
        xml = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url>
            <loc>https://example.com/page1</loc>
            <lastmod>2024-01-01</lastmod>
            <priority>0.8</priority>
          </url>
          <url>
            <loc>https://example.com/page2</loc>
          </url>
        </urlset>"""
        urls = parse_sitemap(xml)
        assert len(urls) == 2

    def test_empty_string(self):
        assert parse_sitemap("") == []

    def test_html_not_xml(self):
        assert parse_sitemap("<html><body>Not a sitemap</body></html>") == []

    def test_oversized_xml_rejected(self):
        """XML larger than _MAX_XML_SIZE is rejected."""
        big_xml = "x" * (_MAX_XML_SIZE + 1)
        assert parse_sitemap(big_xml) == []


# ===========================================================================
# check_robots
# ===========================================================================


class TestCheckRobots:
    def test_allow_all(self):
        robots = "User-agent: *\nAllow: /"
        assert check_robots(robots, "https://example.com/page", "gnosis-mcp/0.8.0") is True

    def test_disallow_all(self):
        robots = "User-agent: *\nDisallow: /"
        assert check_robots(robots, "https://example.com/page", "gnosis-mcp/0.8.0") is False

    def test_disallow_specific_path(self):
        robots = "User-agent: *\nDisallow: /private/"
        assert check_robots(robots, "https://example.com/private/secret", "gnosis-mcp/0.8.0") is False
        assert check_robots(robots, "https://example.com/public/page", "gnosis-mcp/0.8.0") is True

    def test_specific_user_agent_blocked(self):
        robots = "User-agent: badbot\nDisallow: /\n\nUser-agent: *\nAllow: /"
        assert check_robots(robots, "https://example.com/page", "goodbot") is True

    def test_empty_robots(self):
        assert check_robots("", "https://example.com/page", "gnosis-mcp/0.8.0") is True

    def test_disallow_specific_file(self):
        robots = "User-agent: *\nDisallow: /secret.html"
        assert check_robots(robots, "https://example.com/secret.html", "test-agent") is False
        assert check_robots(robots, "https://example.com/other.html", "test-agent") is True

    def test_multiple_disallow_rules(self):
        robots = "User-agent: *\nDisallow: /admin/\nDisallow: /private/\nDisallow: /tmp/"
        assert check_robots(robots, "https://example.com/admin/panel", "bot") is False
        assert check_robots(robots, "https://example.com/private/data", "bot") is False
        assert check_robots(robots, "https://example.com/public/page", "bot") is True

    def test_disallow_subpath(self):
        robots = "User-agent: *\nDisallow: /docs/"
        assert check_robots(robots, "https://example.com/docs/page", "bot") is False
        assert check_robots(robots, "https://example.com/other/page", "bot") is True

    def test_crawl_delay_ignored(self):
        robots = "User-agent: *\nCrawl-delay: 10\nAllow: /"
        assert check_robots(robots, "https://example.com/page", "bot") is True


class TestParseRobots:
    def test_returns_robot_file_parser(self):
        rp = _parse_robots("User-agent: *\nAllow: /")
        assert rp.can_fetch("bot", "https://example.com/page") is True

    def test_disallow(self):
        rp = _parse_robots("User-agent: *\nDisallow: /")
        assert rp.can_fetch("bot", "https://example.com/page") is False


# ===========================================================================
# extract_links
# ===========================================================================


class TestExtractLinks:
    def test_basic_links(self):
        html = '<a href="/page1">Page 1</a><a href="/page2">Page 2</a>'
        links = extract_links(html, "https://example.com/")
        assert "https://example.com/page1" in links
        assert "https://example.com/page2" in links

    def test_absolute_links(self):
        html = '<a href="https://example.com/about">About</a>'
        links = extract_links(html, "https://example.com/")
        assert "https://example.com/about" in links

    def test_filters_external_links(self):
        html = '<a href="https://other.com/page">External</a><a href="/local">Local</a>'
        links = extract_links(html, "https://example.com/", same_host_only=True)
        assert len(links) == 1
        assert "https://example.com/local" in links

    def test_includes_external_when_disabled(self):
        html = '<a href="https://other.com/page">External</a>'
        links = extract_links(html, "https://example.com/", same_host_only=False)
        assert len(links) == 1

    def test_skips_fragment_only_links(self):
        html = '<a href="#section">Section</a>'
        links = extract_links(html, "https://example.com/page")
        assert len(links) == 0

    def test_skips_javascript_links(self):
        html = '<a href="javascript:void(0)">Click</a>'
        links = extract_links(html, "https://example.com/")
        assert len(links) == 0

    def test_skips_mailto_links(self):
        html = '<a href="mailto:test@example.com">Email</a>'
        links = extract_links(html, "https://example.com/")
        assert len(links) == 0

    def test_skips_tel_links(self):
        html = '<a href="tel:+1234567890">Call</a>'
        links = extract_links(html, "https://example.com/")
        assert len(links) == 0

    def test_deduplicates(self):
        html = '<a href="/page">A</a><a href="/page">B</a><a href="/page#s">C</a>'
        links = extract_links(html, "https://example.com/")
        # /page and /page#s normalize to the same URL
        assert len(links) == 1

    def test_resolves_relative_paths(self):
        html = '<a href="../other">Other</a>'
        links = extract_links(html, "https://example.com/docs/page")
        assert "https://example.com/other" in links

    def test_single_quoted_href(self):
        html = "<a href='/page'>Page</a>"
        links = extract_links(html, "https://example.com/")
        assert len(links) == 1

    def test_empty_href(self):
        html = '<a href="">Empty</a>'
        links = extract_links(html, "https://example.com/")
        assert len(links) == 0

    def test_complex_html(self):
        html = """
        <nav>
            <a href="/docs/getting-started" class="nav-link">Getting Started</a>
            <a href="/docs/api-reference" id="api-ref">API Reference</a>
            <a href="https://github.com/example" target="_blank">GitHub</a>
        </nav>
        """
        links = extract_links(html, "https://example.com/", same_host_only=True)
        assert len(links) == 2
        assert "https://example.com/docs/getting-started" in links
        assert "https://example.com/docs/api-reference" in links

    def test_preserves_query_params(self):
        html = '<a href="/search?q=test&page=2">Search</a>'
        links = extract_links(html, "https://example.com/")
        assert any("q=test" in link for link in links)

    def test_non_http_schemes_filtered(self):
        html = '<a href="ftp://files.example.com/doc">FTP</a>'
        links = extract_links(html, "https://example.com/")
        assert len(links) == 0


# ===========================================================================
# url_matches_pattern
# ===========================================================================


class TestUrlMatchesPattern:
    def test_wildcard_match(self):
        assert url_matches_pattern("https://example.com/docs/api/v2", "/docs/*") is True

    def test_exact_match(self):
        assert url_matches_pattern("https://example.com/docs", "/docs") is True

    def test_no_match(self):
        assert url_matches_pattern("https://example.com/blog/post", "/docs/*") is False

    def test_double_wildcard(self):
        assert url_matches_pattern("https://example.com/docs/api/v2/charges", "/docs/api/*") is True

    def test_question_mark(self):
        assert url_matches_pattern("https://example.com/v1", "/v?") is True
        assert url_matches_pattern("https://example.com/v12", "/v?") is False

    def test_root_path(self):
        assert url_matches_pattern("https://example.com/", "/") is True

    def test_nested_pattern(self):
        assert url_matches_pattern("https://example.com/tutorial/basics", "/tutorial/*") is True
        assert url_matches_pattern("https://example.com/api/tutorial/basics", "/tutorial/*") is False

    def test_any_extension(self):
        assert url_matches_pattern("https://example.com/docs/page.html", "/docs/*.html") is True
        assert url_matches_pattern("https://example.com/docs/page.md", "/docs/*.html") is False


# ===========================================================================
# load_cache / save_cache
# ===========================================================================


class TestCacheIO:
    def test_load_missing_file(self, tmp_path):
        cache = load_cache(tmp_path / "missing.json")
        assert cache == {}

    def test_save_and_load(self, tmp_path):
        cache_file = tmp_path / "cache.json"
        data = {"https://example.com/page": {"etag": '"abc"', "hash": "1234", "timestamp": 1.0}}
        save_cache(data, cache_file)
        loaded = load_cache(cache_file)
        assert loaded == data

    def test_creates_parent_dirs(self, tmp_path):
        cache_file = tmp_path / "sub" / "dir" / "cache.json"
        save_cache({"key": "value"}, cache_file)
        assert cache_file.exists()

    def test_load_corrupt_json(self, tmp_path):
        cache_file = tmp_path / "bad.json"
        cache_file.write_text("not json {{{")
        assert load_cache(cache_file) == {}

    def test_overwrite_existing(self, tmp_path):
        cache_file = tmp_path / "cache.json"
        save_cache({"old": "data"}, cache_file)
        save_cache({"new": "data"}, cache_file)
        loaded = load_cache(cache_file)
        assert loaded == {"new": "data"}

    def test_empty_cache(self, tmp_path):
        cache_file = tmp_path / "empty.json"
        save_cache({}, cache_file)
        assert load_cache(cache_file) == {}

    def test_atomic_write_permissions(self, tmp_path):
        """Cache file should have 0o600 permissions."""
        cache_file = tmp_path / "secure.json"
        save_cache({"key": "value"}, cache_file)
        mode = stat.S_IMODE(os.stat(cache_file).st_mode)
        assert mode == 0o600

    def test_atomic_write_no_temp_files_left(self, tmp_path):
        """No temporary files should remain after save."""
        cache_file = tmp_path / "cache.json"
        save_cache({"key": "value"}, cache_file)
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name == "cache.json"


# ===========================================================================
# CrawlResult / CrawlConfig
# ===========================================================================


class TestCrawlResult:
    def test_defaults(self):
        r = CrawlResult(url="https://example.com", chunks=5, action=CrawlAction.CRAWLED)
        assert r.detail == ""

    def test_with_detail(self):
        r = CrawlResult(url="https://example.com", chunks=0, action=CrawlAction.ERROR, detail="timeout")
        assert r.detail == "timeout"

    def test_action_is_str(self):
        r = CrawlResult(url="https://example.com", chunks=0, action=CrawlAction.CRAWLED)
        assert r.action == "crawled"
        assert isinstance(r.action, str)


class TestCrawlConfig:
    def test_defaults(self):
        c = CrawlConfig()
        assert c.sitemap is False
        assert c.depth == 1
        assert c.concurrency == 5
        assert c.delay == 0.2
        assert c.dry_run is False
        assert c.force is False
        assert c.embed is False
        assert c.timeout == 30.0
        assert "gnosis-mcp" in c.user_agent

    def test_custom_values(self):
        c = CrawlConfig(sitemap=True, depth=3, concurrency=10, delay=0.5)
        assert c.sitemap is True
        assert c.depth == 3
        assert c.concurrency == 10
        assert c.delay == 0.5

    def test_max_urls_default(self):
        c = CrawlConfig()
        assert c.max_urls == 5000

    def test_max_urls_custom(self):
        c = CrawlConfig(max_urls=100)
        assert c.max_urls == 100

    def test_frozen(self):
        c = CrawlConfig()
        with pytest.raises(AttributeError):
            c.depth = 5  # type: ignore[misc]

    def test_depth_clamped_to_max(self):
        """Depth exceeding _MAX_DEPTH is clamped."""
        c = CrawlConfig(depth=999)
        assert c.depth == _MAX_DEPTH

    def test_depth_at_max_not_clamped(self):
        c = CrawlConfig(depth=_MAX_DEPTH)
        assert c.depth == _MAX_DEPTH

    def test_depth_below_max_unchanged(self):
        c = CrawlConfig(depth=5)
        assert c.depth == 5


# ===========================================================================
# fetch_page (async)
# ===========================================================================


class TestFetchPage:
    @pytest.mark.asyncio
    async def test_basic_fetch(self):
        from gnosis_mcp.crawl import fetch_page

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>Hello</body></html>"
        mock_response.url = "https://example.com/page"
        mock_response.headers = {
            "content-type": "text/html",
            "etag": '"abc123"',
            "last-modified": "Mon, 01 Jan 2024 00:00:00 GMT",
        }

        client = AsyncMock()
        client.get.return_value = mock_response

        result = await fetch_page(client, "https://example.com/page", {})
        assert result is not None
        assert result.html == "<html><body>Hello</body></html>"
        assert result.etag == '"abc123"'

    @pytest.mark.asyncio
    async def test_304_not_modified(self):
        from gnosis_mcp.crawl import fetch_page

        mock_response = MagicMock()
        mock_response.status_code = 304
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get.return_value = mock_response

        cache = {"https://example.com/page": {"etag": '"old"'}}
        result = await fetch_page(client, "https://example.com/page", cache)
        assert result is None

    @pytest.mark.asyncio
    async def test_sends_conditional_headers(self):
        from gnosis_mcp.crawl import fetch_page

        mock_response = MagicMock()
        mock_response.status_code = 304
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get.return_value = mock_response

        cache = {"https://example.com/page": {"etag": '"abc"', "last_modified": "Mon, 01 Jan 2024"}}
        await fetch_page(client, "https://example.com/page", cache)

        call_kwargs = client.get.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers.get("If-None-Match") == '"abc"'
        assert headers.get("If-Modified-Since") == "Mon, 01 Jan 2024"

    @pytest.mark.asyncio
    async def test_skips_non_html(self):
        from gnosis_mcp.crawl import fetch_page

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.url = "https://example.com/doc.pdf"
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get.return_value = mock_response

        result = await fetch_page(client, "https://example.com/doc.pdf", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_force_ignores_cache(self):
        from gnosis_mcp.crawl import fetch_page

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html>fresh</html>"
        mock_response.url = "https://example.com/page"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get.return_value = mock_response

        cache = {"https://example.com/page": {"etag": '"old"'}}
        result = await fetch_page(client, "https://example.com/page", cache, force=True)
        assert result is not None

        # Should NOT send conditional headers when force=True
        call_kwargs = client.get.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert "If-None-Match" not in headers

    @pytest.mark.asyncio
    async def test_blocks_redirect_to_private_host(self):
        """SSRF: redirect to private host should return None."""
        from gnosis_mcp.crawl import fetch_page

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.url = "http://127.0.0.1/admin"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get.return_value = mock_response

        result = await fetch_page(client, "https://example.com/redirect", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_blocks_oversized_response(self):
        """Response larger than _MAX_RESPONSE_SIZE should return None."""
        from gnosis_mcp.crawl import _MAX_RESPONSE_SIZE, fetch_page

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.url = "https://example.com/big"
        mock_response.headers = {
            "content-type": "text/html",
            "content-length": str(_MAX_RESPONSE_SIZE + 1),
        }
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get.return_value = mock_response

        result = await fetch_page(client, "https://example.com/big", {})
        assert result is None


# ===========================================================================
# extract_content (async)
# ===========================================================================


class TestExtractContent:
    @pytest.mark.asyncio
    async def test_extracts_from_html(self):
        from gnosis_mcp.crawl import extract_content

        html = """<html><body>
        <article>
            <h1>Getting Started</h1>
            <p>This is a comprehensive guide to getting started with our platform.
            It covers installation, configuration, and basic usage patterns that
            you'll need to know.</p>
        </article>
        </body></html>"""
        try:
            result = await extract_content(html, "https://example.com/getting-started")
            # trafilatura may or may not extract enough content
            if result:
                assert len(result) >= 50
        except ImportError:
            pytest.skip("trafilatura not installed")

    @pytest.mark.asyncio
    async def test_returns_none_for_empty(self):
        from gnosis_mcp.crawl import extract_content

        try:
            result = await extract_content("<html><body></body></html>", "https://example.com/")
            assert result is None
        except ImportError:
            pytest.skip("trafilatura not installed")


# ===========================================================================
# discover_urls (async)
# ===========================================================================


class TestDiscoverUrls:
    @pytest.mark.asyncio
    async def test_bfs_basic(self):
        from gnosis_mcp.crawl import discover_urls

        html = '<html><body><a href="/page1">1</a><a href="/page2">2</a></body></html>'
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_response.headers = {"content-type": "text/html"}

        client = AsyncMock()
        client.get.return_value = mock_response

        config = CrawlConfig(depth=1, delay=0)
        urls = await discover_urls(client, "https://example.com/", config)
        assert "https://example.com" in urls or "https://example.com/" in urls

    @pytest.mark.asyncio
    async def test_bfs_respects_depth(self):
        from gnosis_mcp.crawl import discover_urls

        html = '<html><body><a href="/page1">1</a></body></html>'
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_response.headers = {"content-type": "text/html"}

        client = AsyncMock()
        client.get.return_value = mock_response

        config = CrawlConfig(depth=0, delay=0)
        urls = await discover_urls(client, "https://example.com/", config)
        # depth=0 means only the base URL, no crawling of links
        assert len(urls) == 1

    @pytest.mark.asyncio
    async def test_bfs_respects_max_urls(self):
        """BFS stops when max_urls is reached."""
        from gnosis_mcp.crawl import discover_urls

        # Generate HTML with many links
        links_html = "".join(f'<a href="/page{i}">P{i}</a>' for i in range(100))
        html = f"<html><body>{links_html}</body></html>"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_response.headers = {"content-type": "text/html"}

        client = AsyncMock()
        client.get.return_value = mock_response

        config = CrawlConfig(depth=2, delay=0, max_urls=5)
        urls = await discover_urls(client, "https://example.com/", config)
        assert len(urls) <= 5


# ===========================================================================
# crawl_url integration tests (with mock HTTP + real SQLite)
# ===========================================================================


class TestCrawlUrlIntegration:
    @pytest.mark.asyncio
    async def test_dry_run_returns_urls(self, tmp_path, monkeypatch):
        """Dry run should discover URLs but not fetch or ingest."""
        monkeypatch.delenv("GNOSIS_MCP_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        if not _has_httpx():
            pytest.skip("httpx not installed")

        from gnosis_mcp.config import GnosisMcpConfig
        from gnosis_mcp.crawl import crawl_url

        config = GnosisMcpConfig.from_env()

        # Mock httpx to avoid real network calls
        robots_resp = MagicMock()
        robots_resp.status_code = 200
        robots_resp.text = "User-agent: *\nAllow: /"

        sitemap_resp = MagicMock()
        sitemap_resp.status_code = 200
        sitemap_resp.text = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://docs.test.com/page1</loc></url>
          <url><loc>https://docs.test.com/page2</loc></url>
        </urlset>"""

        async def mock_get(url, **kwargs):
            if "robots.txt" in url:
                return robots_resp
            if "sitemap.xml" in url:
                return sitemap_resp
            return robots_resp

        mock_client_instance = AsyncMock()
        mock_client_instance.get = mock_get
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch("gnosis_mcp.crawl._require_httpx") as mock_httpx:
            mock_httpx_module = MagicMock()
            mock_httpx_module.AsyncClient.return_value = mock_client_instance
            mock_httpx.return_value = mock_httpx_module

            crawl_config = CrawlConfig(sitemap=True, dry_run=True)
            cache_file = tmp_path / "test-cache.json"

            results = await crawl_url(config, "https://docs.test.com/", crawl_config, cache_path=cache_file)

        assert len(results) == 2
        assert all(r.action == "dry-run" for r in results)
        assert all(r.chunks == 0 for r in results)

    @pytest.mark.asyncio
    async def test_crawl_with_include_filter(self, tmp_path, monkeypatch):
        """Include filter should restrict which URLs are processed."""
        monkeypatch.delenv("GNOSIS_MCP_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        if not _has_httpx():
            pytest.skip("httpx not installed")

        from gnosis_mcp.config import GnosisMcpConfig
        from gnosis_mcp.crawl import crawl_url

        config = GnosisMcpConfig.from_env()

        robots_resp = MagicMock()
        robots_resp.status_code = 200
        robots_resp.text = "User-agent: *\nAllow: /"

        sitemap_resp = MagicMock()
        sitemap_resp.status_code = 200
        sitemap_resp.text = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://docs.test.com/api/charges</loc></url>
          <url><loc>https://docs.test.com/api/customers</loc></url>
          <url><loc>https://docs.test.com/blog/news</loc></url>
        </urlset>"""

        async def mock_get(url, **kwargs):
            if "robots.txt" in url:
                return robots_resp
            if "sitemap.xml" in url:
                return sitemap_resp
            return robots_resp

        mock_client_instance = AsyncMock()
        mock_client_instance.get = mock_get
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch("gnosis_mcp.crawl._require_httpx") as mock_httpx:
            mock_httpx_module = MagicMock()
            mock_httpx_module.AsyncClient.return_value = mock_client_instance
            mock_httpx.return_value = mock_httpx_module

            crawl_config = CrawlConfig(sitemap=True, dry_run=True, include="/api/*")
            cache_file = tmp_path / "test-cache.json"

            results = await crawl_url(config, "https://docs.test.com/", crawl_config, cache_path=cache_file)

        assert len(results) == 2
        assert all("/api/" in r.url for r in results)

    @pytest.mark.asyncio
    async def test_crawl_with_exclude_filter(self, tmp_path, monkeypatch):
        """Exclude filter should skip matching URLs."""
        monkeypatch.delenv("GNOSIS_MCP_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        if not _has_httpx():
            pytest.skip("httpx not installed")

        from gnosis_mcp.config import GnosisMcpConfig
        from gnosis_mcp.crawl import crawl_url

        config = GnosisMcpConfig.from_env()

        robots_resp = MagicMock()
        robots_resp.status_code = 200
        robots_resp.text = "User-agent: *\nAllow: /"

        sitemap_resp = MagicMock()
        sitemap_resp.status_code = 200
        sitemap_resp.text = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://docs.test.com/api/charges</loc></url>
          <url><loc>https://docs.test.com/blog/news</loc></url>
          <url><loc>https://docs.test.com/blog/update</loc></url>
        </urlset>"""

        async def mock_get(url, **kwargs):
            if "robots.txt" in url:
                return robots_resp
            if "sitemap.xml" in url:
                return sitemap_resp
            return robots_resp

        mock_client_instance = AsyncMock()
        mock_client_instance.get = mock_get
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch("gnosis_mcp.crawl._require_httpx") as mock_httpx:
            mock_httpx_module = MagicMock()
            mock_httpx_module.AsyncClient.return_value = mock_client_instance
            mock_httpx.return_value = mock_httpx_module

            crawl_config = CrawlConfig(sitemap=True, dry_run=True, exclude="/blog/*")
            cache_file = tmp_path / "test-cache.json"

            results = await crawl_url(config, "https://docs.test.com/", crawl_config, cache_path=cache_file)

        assert len(results) == 1
        assert "/api/" in results[0].url

    @pytest.mark.asyncio
    async def test_private_url_blocked(self, tmp_path, monkeypatch):
        """Crawling a private URL should return blocked result."""
        monkeypatch.delenv("GNOSIS_MCP_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        if not _has_httpx():
            pytest.skip("httpx not installed")

        from gnosis_mcp.config import GnosisMcpConfig
        from gnosis_mcp.crawl import crawl_url

        config = GnosisMcpConfig.from_env()

        with patch("gnosis_mcp.crawl._require_httpx") as mock_httpx:
            mock_httpx.return_value = MagicMock()

            crawl_config = CrawlConfig(dry_run=True)
            cache_file = tmp_path / "test-cache.json"

            results = await crawl_url(
                config, "http://127.0.0.1:8080/admin", crawl_config, cache_path=cache_file
            )

        assert len(results) == 1
        assert results[0].action == CrawlAction.BLOCKED
        assert "private" in results[0].detail

    @pytest.mark.asyncio
    async def test_localhost_blocked(self, tmp_path, monkeypatch):
        """Crawling localhost should return blocked result."""
        monkeypatch.delenv("GNOSIS_MCP_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        if not _has_httpx():
            pytest.skip("httpx not installed")

        from gnosis_mcp.config import GnosisMcpConfig
        from gnosis_mcp.crawl import crawl_url

        config = GnosisMcpConfig.from_env()

        with patch("gnosis_mcp.crawl._require_httpx") as mock_httpx:
            mock_httpx.return_value = MagicMock()

            crawl_config = CrawlConfig(dry_run=True)
            cache_file = tmp_path / "test-cache.json"

            results = await crawl_url(
                config, "http://localhost:3000/", crawl_config, cache_path=cache_file
            )

        assert len(results) == 1
        assert results[0].action == CrawlAction.BLOCKED


# ===========================================================================
# _crawl_single
# ===========================================================================


class TestCrawlSingle:
    @pytest.mark.asyncio
    async def test_blocked_by_robots(self):
        from gnosis_mcp.crawl import _crawl_single

        robots = _parse_robots("User-agent: *\nDisallow: /")
        result = await _crawl_single(
            client=AsyncMock(),
            backend=AsyncMock(),
            url="https://example.com/private",
            cache={},
            config=CrawlConfig(delay=0),
            category="example.com",
            has_hash=False,
            has_tags=False,
            robots=robots,
        )
        assert result.action == "blocked"
        assert "robots.txt" in result.detail

    @pytest.mark.asyncio
    async def test_error_handling(self):
        from gnosis_mcp.crawl import _crawl_single

        client = AsyncMock()
        client.get.side_effect = Exception("Connection failed")

        result = await _crawl_single(
            client=client,
            backend=AsyncMock(),
            url="https://example.com/page",
            cache={},
            config=CrawlConfig(delay=0),
            category="example.com",
            has_hash=False,
            has_tags=False,
            robots=None,
        )
        assert result.action == "error"
        assert "Connection failed" in result.detail

    @pytest.mark.asyncio
    async def test_cancelled_error_not_swallowed(self):
        """asyncio.CancelledError must propagate, not be caught as 'error'."""
        from gnosis_mcp.crawl import _crawl_single

        client = AsyncMock()
        client.get.side_effect = asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await _crawl_single(
                client=client,
                backend=AsyncMock(),
                url="https://example.com/page",
                cache={},
                config=CrawlConfig(delay=0),
                category="example.com",
                has_hash=False,
                has_tags=False,
                robots=None,
            )

    @pytest.mark.asyncio
    async def test_no_robots_allows_all(self):
        """When robots=None, all URLs should be allowed (not blocked)."""
        from gnosis_mcp.crawl import _crawl_single

        client = AsyncMock()
        client.get.side_effect = Exception("fetch error")

        result = await _crawl_single(
            client=client,
            backend=AsyncMock(),
            url="https://example.com/page",
            cache={},
            config=CrawlConfig(delay=0),
            category="example.com",
            has_hash=False,
            has_tags=False,
            robots=None,
        )
        # Should NOT be blocked — should reach fetch and get error
        assert result.action == "error"
