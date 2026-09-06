"""Guard: Kubernetes deployment secret inputs must never enter the Docker build context.

The production Dockerfile stage does ``COPY . .``, so the root ``.dockerignore``
is the only filter between a repo checkout and a locally built image. Git-ignoring
``deploy/k8s/overlays/<broker>/secret.env`` keeps credentials out of git but NOT
out of the image: dockerignore patterns match slash-separated relative paths where
``*`` does not cross ``/``, so the pre-existing root-level ``*.env`` never matched
nested overlay files. These tests pin the recursive exclusions that fix that.

Pattern-semantics test runs everywhere; the build-context test is the synthetic
marker check (real Docker daemon required, skipped otherwise).
"""

import fnmatch
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERIGNORE = REPO_ROOT / ".dockerignore"

# Files that must NEVER ship in the image (nested under any overlay).
SECRET_INPUTS = [
    "deploy/k8s/overlays/zerodha/secret.env",
    "deploy/k8s/overlays/groww/secret.env",
    "deploy/k8s/overlays/zerodha/secret.yaml",
    "deploy/k8s/overlays/zerodha/kubeseal-input.secret.env",
    "secret.env",
    "deploy/secret.yaml",
]

# Templates and samples that MUST stay in the context ("keep usable templates").
MUST_KEEP = [
    ".sample.env",
    "deploy/k8s/overlays/_template/secret.env.example",
]


def _load_patterns():
    patterns = []
    for line in DOCKERIGNORE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def _segment_match(pattern: str, path: str) -> bool:
    """Dockerignore segment matching: '**' crosses separators, '*' does not."""
    pseg = pattern.strip("/").split("/")
    fseg = path.split("/")

    def match(pi: int, fi: int) -> bool:
        if pi == len(pseg):
            return fi == len(fseg)
        if pseg[pi] == "**":
            return any(match(pi + 1, k) for k in range(fi, len(fseg) + 1))
        if fi == len(fseg) or not fnmatch.fnmatchcase(fseg[fi], pseg[pi]):
            return False
        return match(pi + 1, fi + 1)

    return match(0, 0)


def _is_excluded(patterns, path: str) -> bool:
    """Mirror moby patternmatcher basics: last matching pattern wins."""
    excluded = False
    for pat in patterns:
        negate = pat.startswith("!")
        if _segment_match(pat[1:] if negate else pat, path):
            excluded = not negate
    return excluded


def test_dockerignore_patterns_exclude_nested_secret_inputs():
    """The recursive exclusions must cover every nested secret input pattern."""
    patterns = _load_patterns()
    for path in SECRET_INPUTS:
        assert _is_excluded(patterns, path), (
            f"{path} would enter the Docker build context — add a recursive "
            f"(**/) exclusion to .dockerignore"
        )


def test_dockerignore_patterns_keep_usable_templates():
    """Exclusions must not swallow templates and sample files."""
    patterns = _load_patterns()
    for path in MUST_KEEP:
        assert not _is_excluded(patterns, path), (
            f"{path} is excluded from the Docker build context — templates "
            f"must remain usable"
        )


def _docker_daemon_available() -> bool:
    """True only when the CLI exists AND a daemon answers (`docker info`).

    Binary presence alone is not enough: runner images that ship the docker
    CLI without a daemon would otherwise false-fail the marker check with
    "Cannot connect to the Docker daemon".
    """
    if shutil.which("docker") is None:
        return False
    try:
        return (
            subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=30,
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(
    not _docker_daemon_available(),
    reason="docker daemon not reachable",
)
def test_docker_build_context_excludes_secret_inputs():
    """Synthetic-marker check against the real Docker context.

    Plants marker files matching every secret input pattern inside a fake
    overlay, builds a one-step image that copies the context, and fails the
    build if any marker survived .dockerignore (or if the template vanished).
    """
    marker_dir = REPO_ROOT / "deploy" / "k8s" / "overlays" / "_dockerignore_marker"
    markers = ["secret.env", "secret.yaml", "marker.secret.env"]
    dockerfile = (
        "FROM busybox:latest\n"
        "COPY . /ctx\n"
        "RUN for f in "
        + " ".join(f"ctx/deploy/k8s/overlays/_dockerignore_marker/{m}" for m in markers)
        + "; do [ ! -e \"$f\" ] || { echo \"LEAKED: $f\"; exit 1; }; done "
        "&& [ -e ctx/deploy/k8s/overlays/_template/secret.env.example ] "
        "|| { echo 'MISSING: secret.env.example template'; exit 1; }\n"
    )
    tag = "openalgo-dockerignore-check:ci"
    try:
        marker_dir.mkdir(parents=True, exist_ok=True)
        for m in markers:
            (marker_dir / m).write_text("MARKER-NOT-A-REAL-SECRET\n")
        result = subprocess.run(
            ["docker", "build", "-t", tag, "-f", "-", "."],
            input=dockerfile,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=900,
        )
        leaked = [line for line in result.stdout.splitlines() if "LEAKED" in line or "MISSING" in line]
        assert result.returncode == 0, (
            "secret marker(s) entered the Docker build context:\n"
            + "\n".join(leaked or result.stdout[-2000:] + result.stderr[-2000:])
        )
    finally:
        shutil.rmtree(marker_dir, ignore_errors=True)
        subprocess.run(
            ["docker", "rmi", "-f", tag],
            capture_output=True,
            timeout=120,
        )
