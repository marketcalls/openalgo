from __future__ import annotations

from pathlib import Path


def build_source_library_catalog(source_root: str | Path) -> list[dict[str, object]]:
    root = Path(source_root)
    opensource_root = root / "opensource_indicators"
    catalog: list[dict[str, object]] = []
    if not opensource_root.exists():
        return catalog

    for repo_dir in sorted([path for path in opensource_root.iterdir() if path.is_dir()]):
        python_files = list(repo_dir.rglob("*.py"))
        top_level_items = [path.name for path in sorted(repo_dir.iterdir())[:8]]
        catalog.append(
            {
                "name": repo_dir.name,
                "path": str(repo_dir),
                "python_file_count": len(python_files),
                "top_level_items": top_level_items,
            }
        )
    return catalog
