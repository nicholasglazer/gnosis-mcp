"""File watcher for auto-ingestion of changed markdown files."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from threading import Event, Thread
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gnosis_mcp.config import GnosisMcpConfig

__all__ = ["start_watcher", "scan_mtimes", "detect_changes"]

log = logging.getLogger("gnosis_mcp")

_DEFAULT_INTERVAL = 1.0
_DEBOUNCE = 0.5


def scan_mtimes(root: Path) -> dict[Path, float]:
    """Get mtime for all .md files under root."""
    mtimes: dict[Path, float] = {}
    if not root.exists():
        return mtimes
    if root.is_file() and root.suffix == ".md":
        try:
            mtimes[root] = root.stat().st_mtime
        except OSError:
            pass
        return mtimes
    for f in root.rglob("*.md"):
        try:
            mtimes[f] = f.stat().st_mtime
        except OSError:
            pass
    return mtimes


def detect_changes(
    old: dict[Path, float], new: dict[Path, float]
) -> tuple[list[Path], list[Path]]:
    """Compare mtime snapshots. Returns (changed, deleted) file lists."""
    changed = [p for p, mt in new.items() if p not in old or old[p] != mt]
    deleted = [p for p in old if p not in new]
    return changed, deleted


async def _process_changes(root: str, config: GnosisMcpConfig, embed: bool) -> int:
    """Re-ingest changed files and optionally embed. Returns ingested count."""
    from gnosis_mcp.ingest import ingest_path

    results = await ingest_path(config=config, root=root)
    ingested = sum(1 for r in results if r.action == "ingested")
    unchanged = sum(1 for r in results if r.action == "unchanged")

    if ingested:
        log.info("Watch: ingested %d files (%d unchanged)", ingested, unchanged)

    if embed and ingested > 0:
        provider = config.embed_provider
        if not provider:
            try:
                import onnxruntime  # noqa: F401
                import tokenizers  # noqa: F401

                provider = "local"
            except ImportError:
                return ingested

        from gnosis_mcp.embed import embed_pending

        model = config.embed_model
        if provider == "local" and not config.embed_provider:
            model = "MongoDB/mdbr-leaf-ir"

        result = await embed_pending(
            config=config,
            provider=provider,
            model=model,
            api_key=config.embed_api_key,
            url=config.embed_url,
            batch_size=config.embed_batch_size,
            dim=config.embed_dim,
        )
        if result.embedded > 0:
            log.info("Watch: embedded %d chunks", result.embedded)

    return ingested


def _watch_loop(
    root: str,
    config: GnosisMcpConfig,
    embed: bool,
    interval: float,
    stop_event: Event,
) -> None:
    """Blocking watch loop. Runs in a daemon thread."""
    root_path = Path(root).resolve()
    mtimes = scan_mtimes(root_path)
    log.info("Watching %s (%d files, interval: %.1fs)", root_path, len(mtimes), interval)

    while not stop_event.is_set():
        stop_event.wait(interval)
        if stop_event.is_set():
            break

        new_mtimes = scan_mtimes(root_path)
        changed, deleted = detect_changes(mtimes, new_mtimes)

        if not changed and not deleted:
            continue

        # Debounce: wait for rapid writes to settle, then re-scan
        stop_event.wait(_DEBOUNCE)
        if stop_event.is_set():
            break
        new_mtimes = scan_mtimes(root_path)

        mtimes = new_mtimes

        names = [p.name for p in changed]
        if names:
            log.info("Changes detected: %s", ", ".join(names[:5]))
            if len(names) > 5:
                log.info("  ... and %d more", len(names) - 5)
        if deleted:
            log.info("Deleted: %s", ", ".join(p.name for p in deleted[:5]))

        try:
            asyncio.run(_process_changes(root, config, embed))
        except Exception:
            log.exception("Watch: error processing changes")


def start_watcher(
    root: str,
    config: GnosisMcpConfig,
    *,
    embed: bool = True,
    interval: float = _DEFAULT_INTERVAL,
) -> Thread:
    """Start a background file watcher thread.

    Monitors ``root`` for ``.md`` file changes and auto-re-ingests (and optionally
    auto-embeds) when changes are detected.  Uses polling with mtime comparison.

    Args:
        root: Directory or file path to watch.
        config: GnosisMcpConfig instance.
        embed: Auto-embed new chunks when ``[embeddings]`` is installed.
        interval: Polling interval in seconds.

    Returns:
        The watcher thread (daemon, already started).
        Set ``thread.stop_event.set()`` to stop.
    """
    stop_event = Event()
    thread = Thread(
        target=_watch_loop,
        args=(root, config, embed, interval, stop_event),
        daemon=True,
        name="gnosis-watcher",
    )
    thread.stop_event = stop_event  # type: ignore[attr-defined]
    thread.start()
    return thread
