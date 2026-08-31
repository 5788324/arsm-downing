"""Local sidecar asset discovery shared by downloads and library views."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
COVER_EXACT_NAMES = {
    "cover.jpg", "cover.jpeg", "cover.png", "cover.webp",
    "main.jpg", "main.jpeg", "main.png", "main.webp",
    "package.jpg", "package.jpeg", "package.png", "package.webp",
    "folder.jpg", "folder.jpeg", "folder.png", "folder.webp",
}
COVER_KEYWORDS = (
    "cover", "main", "package", "jacket", "front", "folder",
    "封面", "表紙",
)


def is_cover_filename(name: str | Path) -> bool:
    path = Path(name)
    lowered = path.name.casefold()
    if path.suffix.casefold() not in COVER_EXTENSIONS:
        return False
    return (
        lowered in COVER_EXACT_NAMES
        or any(token in lowered for token in COVER_KEYWORDS)
    )


def _first_named_cover(paths: Iterable[Path]) -> Path | None:
    candidates = sorted(
        (path for path in paths
         if not path.is_symlink()
         and path.is_file() and is_cover_filename(path)),
        key=lambda path: (
            0 if path.name.casefold() in COVER_EXACT_NAMES else 1,
            path.name.casefold(),
        ),
    )
    return candidates[0] if candidates else None


def find_local_cover(root: str | Path) -> Path | None:
    """Find a likely cover without ever following links outside the album."""
    album = Path(root)
    if album.is_symlink() or not album.is_dir():
        return None
    try:
        direct_files = [path for path in album.iterdir() if path.is_file()]
    except OSError:
        return None
    direct = _first_named_cover(direct_files)
    if direct is not None:
        return direct
    direct_images = sorted(
        (path for path in direct_files
         if path.suffix.casefold() in COVER_EXTENSIONS),
        key=lambda path: path.name.casefold(),
    )
    if len(direct_images) == 1:
        return direct_images[0]

    try:
        for current_root, dir_names, file_names in os.walk(album, followlinks=False):
            current = Path(current_root)
            dir_names[:] = sorted(
                name for name in dir_names
                if not (current / name).is_symlink()
            )
            nested = _first_named_cover(
                current / name for name in sorted(file_names)
            )
            if nested is not None:
                return nested
    except OSError:
        return None
    return None
