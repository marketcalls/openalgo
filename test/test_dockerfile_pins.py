"""Every Dockerfile base image must be pinned to an immutable digest (issue #1857).

A `FROM` line carrying only a mutable tag can resolve to different content
between builds, weakening reproducibility and supply-chain review. Once a
digest is present, BuildKit resolves by digest and the tag becomes purely
cosmetic - so this also guards against tag and digest drifting apart (e.g.
someone retargeting a stage to a new tag without updating the digest, which
would leave the build silently pinned to the old, stale image).
"""

import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCKERFILE_PATH = os.path.join(REPO_ROOT, "Dockerfile")

FROM_LINE_RE = re.compile(r"^FROM\s+(\S+)", re.MULTILINE)
DIGEST_SUFFIX_RE = re.compile(r"@sha256:[0-9a-f]{64}$")


def _from_image_refs():
    with open(DOCKERFILE_PATH) as f:
        content = f.read()
    return FROM_LINE_RE.findall(content)


def test_dockerfile_has_from_lines():
    image_refs = _from_image_refs()
    assert image_refs, f"no FROM lines found in {DOCKERFILE_PATH}"


def test_every_from_line_is_pinned_to_a_digest():
    image_refs = _from_image_refs()

    unpinned = [ref for ref in image_refs if not DIGEST_SUFFIX_RE.search(ref)]
    assert not unpinned, (
        "Dockerfile FROM line(s) missing an @sha256:<64 hex chars> digest pin: "
        f"{unpinned}"
    )
