"""Build the Windows desktop release zip.

    uv run python scripts/build_release.py              # from a clean tree
    uv run python scripts/build_release.py --allow-dirty

Writes ``release/<Product>-<version>.zip`` and a ``.sha256`` beside it. The zip
holds one folder:

    <Product>-<version>/
      Install <Product>.cmd     what the client double-clicks
      install-desktop.ps1       the installer it runs
      app/                      the source tree, with no Git information
        RELEASE_FILES           every file shipped, read by the reset (launcher.state)

The source is every file Git tracks plus new files not ignored, as they are in
the working tree, so the built ``frontend/dist`` goes in as it is: build it
first. Nothing from ``.git`` and nothing gitignored is included, which keeps
``.env``, databases and logs out.

See M3.5 in ``docs/plans/2026-11-05-desktop-panel-and-reset-plan.md``.
"""

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from launcher.branding import product_name  # noqa: E402
from launcher.state import RELEASE_LIST  # noqa: E402

INSTALLER_DIR = REPO / "install" / "desktop"


def version() -> str:
    match = re.search(
        r'^VERSION\s*=\s*"([^"]+)"',
        (REPO / "utils" / "version.py").read_text(encoding="utf-8"),
        re.M,
    )
    if not match:
        raise SystemExit("utils/version.py has no VERSION")
    return match.group(1)


def git(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, check=True, timeout=120
    ).stdout


def source_files() -> list[str]:
    listed = (
        git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
        .decode("utf-8")
        .split("\0")
    )
    # A tracked file deleted in the working tree is not shipped.
    return sorted(p for p in set(listed) if p and (REPO / p).is_file())


def checks(allow_dirty: bool) -> None:
    if not allow_dirty and git("status", "--porcelain").strip():
        raise SystemExit(
            "The working tree has uncommitted changes. Commit them, or pass --allow-dirty for a test build."
        )
    if not (REPO / "frontend" / "dist" / "index.html").is_file():
        raise SystemExit(
            "frontend/dist is missing. Build the frontend first (cd frontend && npm run build)."
        )
    node = shutil.which("node")
    if node:
        result = subprocess.run(
            [node, "scripts/brand-check.mjs"], cwd=REPO, capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            print(result.stdout[-2000:])
            raise SystemExit(
                "brand-check found upstream branding that would reach a user. Fix it before releasing."
            )
    else:
        print("Warning: Node.js not found, so scripts/brand-check.mjs was not run.")


def crlf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def build(out_dir: Path, allow_dirty: bool) -> Path:
    checks(allow_dirty)
    name, ver = product_name(REPO), version()
    top = f"{name}-{ver}"
    files = [
        f for f in source_files() if not f.startswith(f"{out_dir.relative_to(REPO).as_posix()}/")
    ]
    shipped = files + [RELEASE_LIST]

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{top}.zip"
    partial = target.with_suffix(".zip.partial")
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr(f"{top}/Install {name}.cmd", crlf((INSTALLER_DIR / "Install.cmd").read_bytes()))
        zf.writestr(
            f"{top}/install-desktop.ps1", crlf((INSTALLER_DIR / "install-desktop.ps1").read_bytes())
        )
        for rel in files:
            zf.write(REPO / rel, f"{top}/app/{rel}")
        zf.writestr(f"{top}/app/{RELEASE_LIST}", "\n".join(shipped) + "\n")
    partial.replace(target)

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_name(target.name + ".sha256").write_text(
        f"{digest}  {target.name}\n", encoding="utf-8"
    )
    print(f"{target}  ({target.stat().st_size / 1_048_576:.1f} MB, {len(files)} files)")
    print(f"sha256 {digest}")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Windows desktop release zip.")
    parser.add_argument(
        "--out", type=Path, default=REPO / "release", help="output folder (default: release/)"
    )
    parser.add_argument(
        "--allow-dirty", action="store_true", help="build with uncommitted changes (test builds)"
    )
    args = parser.parse_args(argv)
    build(args.out.resolve(), args.allow_dirty)
    return 0


if __name__ == "__main__":
    sys.exit(main())
