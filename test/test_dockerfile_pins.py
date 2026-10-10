"""Every Dockerfile base image must be pinned to an immutable digest (issue #1857).

A `FROM` line carrying only a mutable tag can resolve to different content
between builds, weakening reproducibility and supply-chain review. This test
guards against a stage missing its digest pin entirely, e.g. a new stage
added without one, or an existing pin dropped by accident.

It does not, and cannot without a network call, verify that a pinned digest
still matches what its tag currently resolves to on the registry. That is a
live registry fact, checked manually with `docker buildx imagetools inspect
<tag>` when a pin is refreshed, not something this offline test can assert.

`FROM <earlier-stage> AS <name>` (a stage building on a previous stage,
rather than an external image) is excluded: the referenced name is a local
alias declared by this same Dockerfile, not something that needs its own
digest.
"""

import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCKERFILE_PATH = os.path.join(REPO_ROOT, "Dockerfile")

# Leading whitespace is valid before an instruction, instruction names are
# case-insensitive, and `--platform=...`-style flags may sit between FROM
# and the image reference.
FROM_LINE_RE = re.compile(
    r"^[ \t]*FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+(\S+))?",
    re.MULTILINE | re.IGNORECASE,
)
DIGEST_SUFFIX_RE = re.compile(r"@sha256:[0-9a-f]{64}$")


def _from_instructions():
    with open(DOCKERFILE_PATH, encoding="utf-8") as f:
        content = f.read()
    return FROM_LINE_RE.findall(content)


def _external_image_refs():
    """FROM targets that reference an external image, not an earlier build stage."""
    instructions = _from_instructions()
    stage_aliases = {alias for _, alias in instructions if alias}
    return [ref for ref, _ in instructions if ref not in stage_aliases]


# Sanity check: if the parser regressed and matched nothing, the digest test
# below would pass vacuously on an empty list. This catches that silently.
def test_dockerfile_has_from_lines():
    assert _from_instructions(), f"no FROM lines found in {DOCKERFILE_PATH}"


# The actual guard: every FROM that targets an external image (not a
# reference to an earlier stage) must carry an @sha256 digest pin.
def test_every_external_from_is_pinned_to_a_digest():
    image_refs = _external_image_refs()
    assert image_refs, f"no external (non-stage) FROM lines found in {DOCKERFILE_PATH}"

    unpinned = [ref for ref in image_refs if not DIGEST_SUFFIX_RE.search(ref)]
    assert not unpinned, (
        f"Dockerfile FROM line(s) missing an @sha256:<64 hex chars> digest pin: {unpinned}"
    )
