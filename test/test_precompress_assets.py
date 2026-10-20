"""Tests for runtime generation and serving of pre-compressed frontend assets.

The ``.gz`` siblings of the built assets are no longer committed with
``frontend/dist/`` (they were two thirds of the repository history), so they are
regenerated at startup by ``utils.precompress_assets``. That makes asset
delivery depend on code rather than on files in the tree, which is worth
covering: a silent failure here degrades every page load, and because assets are
served ``Cache-Control: immutable`` for a year, a corrupt variant is not
self-correcting.
"""

import gzip

import pytest

from utils.precompress_assets import ensure_precompressed_assets


@pytest.fixture
def dist(tmp_path):
    """A miniature dist tree: one compressible asset, one too small, one binary."""
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app-abc123.js").write_bytes(b"const x = 1;\n" * 400)
    (assets / "styles-def456.css").write_bytes(b".a{color:red}\n" * 400)
    (assets / "tiny.js").write_bytes(b"x=1")
    (assets / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 4000)
    (tmp_path / "index.html").write_bytes(b"<!doctype html><body>" + b"a" * 2000)
    return tmp_path


def test_generates_variants_for_compressible_assets(dist):
    ensure_precompressed_assets(dist)

    assert (dist / "assets" / "app-abc123.js.gz").is_file()
    assert (dist / "assets" / "styles-def456.css.gz").is_file()
    assert (dist / "index.html.gz").is_file(), "root-level assets must be covered too"


def test_skips_small_and_incompressible_files(dist):
    ensure_precompressed_assets(dist)

    # Below the 1 KB threshold, gzip framing would cost more than it saves.
    assert not (dist / "assets" / "tiny.js.gz").exists()
    # Not a compressible type, and a PNG is already deflated.
    assert not (dist / "assets" / "logo.png.gz").exists()


def test_variant_roundtrips_to_the_exact_source_bytes(dist):
    ensure_precompressed_assets(dist)

    source = dist / "assets" / "app-abc123.js"
    variant = dist / "assets" / "app-abc123.js.gz"
    assert gzip.decompress(variant.read_bytes()) == source.read_bytes()
    assert variant.stat().st_size < source.stat().st_size


def test_is_idempotent_and_does_not_rewrite_current_variants(dist):
    ensure_precompressed_assets(dist)
    variant = dist / "assets" / "app-abc123.js.gz"
    first = variant.stat().st_mtime_ns

    ensure_precompressed_assets(dist)

    assert variant.stat().st_mtime_ns == first, "an up-to-date variant was rewritten"


def test_regenerates_when_the_source_changes(dist):
    """The `git pull` case: a new build must not be served last build's bytes."""
    ensure_precompressed_assets(dist)
    source = dist / "assets" / "app-abc123.js"
    variant = dist / "assets" / "app-abc123.js.gz"
    stale = variant.read_bytes()

    source.write_bytes(b"const y = 2;\n" * 400)
    ensure_precompressed_assets(dist)

    assert variant.read_bytes() != stale
    assert gzip.decompress(variant.read_bytes()) == source.read_bytes()


def test_removes_variants_whose_source_is_gone(dist):
    """Content-hashed names change every build; without this, dist grows forever."""
    ensure_precompressed_assets(dist)
    orphan = dist / "assets" / "app-abc123.js.gz"
    (dist / "assets" / "app-abc123.js").unlink()

    ensure_precompressed_assets(dist)

    assert not orphan.exists()


def test_removes_the_variant_when_compression_stops_helping(dist):
    """An asset rewritten in place with incompressible bytes must lose its .gz.

    `serve_assets` prefers any .gz sibling for a gzip client, so a variant left
    behind here is served *instead of* the asset, and it is cached immutable for
    a year. The variant must exist only while it holds a smaller, current
    encoding of the file next to it.
    """
    import os

    source = dist / "assets" / "app-abc123.js"
    variant = dist / "assets" / "app-abc123.js.gz"
    ensure_precompressed_assets(dist)
    assert variant.is_file()

    source.write_bytes(os.urandom(4096))  # same name, no longer compressible
    ensure_precompressed_assets(dist)

    assert not variant.exists()


def test_removes_the_variant_when_the_source_drops_below_the_threshold(dist):
    """Same hazard, reached by the asset shrinking rather than by entropy."""
    source = dist / "assets" / "app-abc123.js"
    variant = dist / "assets" / "app-abc123.js.gz"
    ensure_precompressed_assets(dist)
    assert variant.is_file()

    source.write_bytes(b"x=1")  # under _MIN_SOURCE_BYTES, no longer a candidate
    ensure_precompressed_assets(dist)

    assert not variant.exists()


def test_never_serves_a_stale_variant_after_an_in_place_rewrite(dist, monkeypatch):
    """The user-visible consequence of the two cases above."""
    import os

    flask = pytest.importorskip("flask")
    from blueprints import react_app

    monkeypatch.setattr(react_app, "FRONTEND_DIST", dist)
    source = dist / "assets" / "app-abc123.js"
    ensure_precompressed_assets(dist)
    stale = source.read_bytes()

    source.write_bytes(os.urandom(4096))
    ensure_precompressed_assets(dist)

    app = flask.Flask(__name__)
    app.register_blueprint(react_app.react_bp)
    got = app.test_client().get("/assets/app-abc123.js", headers={"Accept-Encoding": "gzip"})

    body = (
        gzip.decompress(got.get_data())
        if got.headers.get("Content-Encoding") == "gzip"
        else got.get_data()
    )
    assert body == source.read_bytes()
    assert body != stale


def test_sweeps_temporaries_from_an_interrupted_run(dist):
    leftover = dist / "assets" / "app-abc123.js.gz.tmp"
    leftover.write_bytes(b"partial")

    ensure_precompressed_assets(dist)

    assert not leftover.exists()


def test_never_raises_on_a_missing_or_unreadable_tree(tmp_path):
    """Compression is an optimisation; it must not be able to stop startup."""
    ensure_precompressed_assets(tmp_path / "no_such_dist")
    ensure_precompressed_assets(tmp_path / "no_such_dist" / "deeper")


def test_serving_negotiates_the_generated_variant(dist, monkeypatch):
    """End-to-end: what the generator writes is what serve_assets hands back."""
    flask = pytest.importorskip("flask")
    from blueprints import react_app

    monkeypatch.setattr(react_app, "FRONTEND_DIST", dist)
    ensure_precompressed_assets(dist)

    app = flask.Flask(__name__)
    app.register_blueprint(react_app.react_bp)
    client = app.test_client()

    got = client.get("/assets/app-abc123.js", headers={"Accept-Encoding": "gzip"})
    assert got.status_code == 200
    assert got.headers["Content-Encoding"] == "gzip"
    assert got.headers["Vary"] == "Accept-Encoding"
    # Flask decodes Content-Encoding on the test client, so compare the source.
    assert gzip.decompress(got.get_data()) == (dist / "assets" / "app-abc123.js").read_bytes()

    # A client that refuses gzip must still get a correct, uncompressed asset.
    plain = client.get("/assets/app-abc123.js", headers={"Accept-Encoding": "identity"})
    assert plain.status_code == 200
    assert "Content-Encoding" not in plain.headers
    assert plain.headers["Vary"] == "Accept-Encoding"
    assert plain.get_data() == (dist / "assets" / "app-abc123.js").read_bytes()
