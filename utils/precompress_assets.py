"""Generate gzip variants of the built frontend assets at startup.

``frontend/dist/`` is committed to ``main`` so that production servers and
backend-only contributors can upgrade with a plain ``git pull`` and never need
Node.js. The pre-compressed ``.gz`` siblings used to be committed alongside the
raw assets, which was expensive in a way that is invisible in a working tree:
gzip output is incompressible, so git can neither deflate a ``.gz`` blob nor
delta it against the previous build's, and Vite's content-hashed filenames mean
every rebuild adds brand new blobs that never go away. Across roughly thirty CI
rebuilds a month those variants grew to two thirds of the repository history and
tripled clone times, all to carry bytes that are perfectly reproducible from the
raw assets sitting next to them.

So they are generated here instead, once per build, from the tracked originals.
The whole ``dist`` tree compresses in about a tenth of a second, the work is
skipped entirely when the variants are already current, and
``blueprints/react_app.py`` serves whatever it finds. Nothing here is required
for correctness: if this fails, or is not run at all, asset negotiation falls
back to the raw file.

Only gzip is produced. Brotli would save a further ~15% but needs a third-party
extension, and the deployments that benefit are a thin slice: OpenAlgo
recommends Cloudflare, which re-compresses at the edge with brotli regardless of
what the origin sends, the Docker install's nginx sets ``gzip on`` for proxied
responses, and laptop installs serve over loopback where the wire size is moot.
That leaves a direct Ubuntu install exposed to the internet without a CDN, which
pays roughly 260 KB extra on a first visit against assets cached ``immutable``
for a year. Not worth a dependency. To reinstate it, add ``brotli`` and mirror
``_write_variant`` for ``.br``; the serving side already negotiates it.
"""

from __future__ import annotations

import gzip
import os
from pathlib import Path

from utils.logging import get_logger

logger = get_logger(__name__)

# Mirrors vite-plugin-compression2's default `include` set. Keeping the two in
# step matters: a developer's local `npm run build` and a production server's
# startup pass must produce the same set of variants, or an asset compresses in
# one environment and not the other.
_COMPRESSIBLE_SUFFIXES = frozenset(
    {".css", ".html", ".js", ".json", ".mjs", ".svg", ".toml", ".xml", ".yaml", ".yml"}
)

# Below this the gzip framing overhead outweighs the saving, and it is the
# threshold the Vite plugin was configured with.
_MIN_SOURCE_BYTES = 1024

_GZIP_SUFFIX = ".gz"

# Level 9 over the full dist costs ~0.11s, so there is nothing to buy by
# trading ratio for speed here.
_GZIP_LEVEL = 9


def _is_compressible(path: Path) -> bool:
    """Whether ``path`` is a raw asset large enough to be worth compressing."""
    if not path.is_file():
        return False
    if path.suffix == _GZIP_SUFFIX:
        return False
    if path.suffix.lower() not in _COMPRESSIBLE_SUFFIXES:
        return False
    return path.stat().st_size >= _MIN_SOURCE_BYTES


def _is_current(source: Path, variant: Path) -> bool:
    """Whether ``variant`` was generated from the present contents of ``source``.

    Compares mtimes rather than hashing: a ``git pull`` stamps every file it
    rewrites with the checkout time, so a variant older than its source is
    exactly the stale case that needs regenerating. A zero-length variant is
    treated as stale so that a run interrupted before ``os.replace`` cannot
    leave an empty file that would be served as a valid empty asset.
    """
    try:
        variant_stat = variant.stat()
    except OSError:
        return False
    return variant_stat.st_size > 0 and variant_stat.st_mtime >= source.stat().st_mtime


def _remove_variant(variant: Path) -> bool:
    """Delete a variant that must not exist, returning whether one was there.

    The invariant this enforces is that ``<asset>.gz`` exists **only** when it
    holds a smaller, current encoding of ``<asset>``. Leaving one behind that no
    longer matches is worse than having none at all: ``serve_assets`` prefers
    any ``.gz`` sibling for a client that advertises gzip, so a stale variant is
    served *in place of* the asset, and it is cached ``immutable`` for a year.
    """
    try:
        variant.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        logger.warning(f"Could not remove stale asset variant {variant}")
        return False


def _write_variant(source: Path, variant: Path) -> bool:
    """Compress ``source`` to ``variant``, returning whether it was written.

    Writes to a temporary sibling and renames, because these assets are served
    with ``Cache-Control: immutable`` for a year: a torn write observed by a
    client would be cached as the definitive copy of a content-hashed URL and
    could not be corrected by a rebuild. ``os.replace`` is atomic on POSIX and
    on Windows, so a reader sees either the old variant or the complete new one.

    When compression does not shrink the asset there must be no variant at all,
    so any existing one is removed rather than left in place. Returning early
    without that removal would strand the *previous* build's bytes next to an
    asset rewritten in place, and gzip clients would be served those bytes
    instead of the current file.
    """
    raw = source.read_bytes()
    compressed = gzip.compress(raw, _GZIP_LEVEL, mtime=0)
    if len(compressed) >= len(raw):
        _remove_variant(variant)
        return False
    tmp = variant.with_name(variant.name + ".tmp")
    try:
        tmp.write_bytes(compressed)
        os.replace(tmp, variant)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    return True


def _remove_orphans(dist_root: Path) -> int:
    """Delete variants whose source asset no longer exists.

    Content-hashed filenames change on every build, so without this every
    upgrade would leave the previous build's variants behind forever and the
    directory would grow without bound across a server's lifetime.
    """
    removed = 0
    for variant in dist_root.rglob("*" + _GZIP_SUFFIX):
        if not variant.is_file():
            continue
        if variant.with_suffix("").exists():
            continue
        try:
            variant.unlink()
            removed += 1
        except OSError:
            logger.warning(f"Could not remove orphaned asset variant {variant}")

    # Sweep temporaries from a run that died between write and rename. They are
    # never served, but without this they would accumulate one per interrupted
    # boot for the life of the server.
    for leftover in dist_root.rglob("*" + _GZIP_SUFFIX + ".tmp"):
        try:
            leftover.unlink()
            removed += 1
        except OSError:
            logger.warning(f"Could not remove stale temporary {leftover}")
    return removed


def ensure_precompressed_assets(dist_root: Path) -> None:
    """Bring the gzip variants under ``dist_root`` up to date with its assets.

    Idempotent and safe to call on every boot: a tree whose variants are already
    current does a stat pass and no writes. Never raises, since compression is a
    bandwidth optimisation and must not be able to stop the app from starting.

    Args:
        dist_root: The built frontend directory, normally ``frontend/dist``.
    """
    try:
        if not dist_root.is_dir():
            return

        written = 0
        skipped = 0
        failed = 0
        removed_stale = 0
        for source in dist_root.rglob("*"):
            try:
                if not source.is_file():
                    continue
                name = source.name
                if name.endswith(_GZIP_SUFFIX) or name.endswith(_GZIP_SUFFIX + ".tmp"):
                    continue  # our own output; the sweep below owns these
                variant = source.with_name(name + _GZIP_SUFFIX)
                if not _is_compressible(source):
                    # It may have had a variant on a previous build and stopped
                    # qualifying since, by shrinking below the threshold or
                    # changing type. The old variant would otherwise keep being
                    # served in place of the asset, so drop it.
                    if _remove_variant(variant):
                        removed_stale += 1
                    continue
                if _is_current(source, variant):
                    skipped += 1
                    continue
                if _write_variant(source, variant):
                    written += 1
            except OSError:
                # Isolated per file on purpose. One asset that cannot be read or
                # written (a permissions oddity, a half-finished build) must not
                # cost the other 157 their compression; that asset simply falls
                # back to being served raw.
                logger.warning(f"Could not compress {source}, serving it raw")
                failed += 1

        removed = _remove_orphans(dist_root) + removed_stale

        if written or removed or failed:
            logger.info(
                f"Frontend asset compression: {written} written, "
                f"{skipped} already current, {removed} stale removed, "
                f"{failed} failed"
            )
        else:
            logger.debug(f"Frontend asset compression: {skipped} variants already current")
    except Exception:
        # Deliberately broad: every failure mode here (read-only dist, partial
        # build, permissions) degrades to serving raw assets, which is correct.
        logger.exception("Could not generate pre-compressed frontend assets")
