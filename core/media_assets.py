"""Local sidecar asset discovery shared by downloads and library views."""
from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Iterable

from PIL import Image, UnidentifiedImageError

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


COVER_DIRECTORY_KEYWORDS = (
    "cover", "jacket", "package", "front", "封面", "表紙",
)
COVER_REJECT_KEYWORDS = (
    "banner", "logo", "sample", "thumb", "thumbnail", "wallpaper",
    "scene", "comic", "cg", "差分", "壁纸", "漫畫", "漫画",
)
_RJ_COVER_NAME = re.compile(r"^rj\d{6,8}(?:[-_ ](?:cover|main|jacket))?$", re.I)

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

def _path_signals_cover(path: Path, album: Path) -> bool:
    """Recognize covers stored under a dedicated folder or named after the RJ id."""
    try:
        relative = path.relative_to(album)
    except ValueError:
        return False
    if _RJ_COVER_NAME.fullmatch(path.stem):
        return True
    return any(
        any(token in part.casefold() for token in COVER_DIRECTORY_KEYWORDS)
        for part in relative.parts[:-1]
    )


def _visual_cover_rank(path: Path, album: Path) -> tuple | None:
    """Return a conservative rank for otherwise unnamed cover-like images."""
    try:
        relative = path.relative_to(album)
        lowered = "/".join(relative.parts).casefold()
        if any(token in lowered for token in COVER_REJECT_KEYWORDS):
            return None
        with Image.open(path) as image:
            width, height = image.size
        if width < 300 or height < 300:
            return None
        ratio = width / height
        if not 0.55 <= ratio <= 1.45:
            return None
        depth = len(relative.parts) - 1
        return (depth, abs(ratio - 0.75), -(width * height), lowered)
    except (OSError, ValueError, UnidentifiedImageError):
        return None



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

    nested_images: list[Path] = []
    try:
        for current_root, dir_names, file_names in os.walk(album, followlinks=False):
            current = Path(current_root)
            dir_names[:] = sorted(
                name for name in dir_names
                if not (current / name).is_symlink()
            )
            files = [current / name for name in sorted(file_names)]
            nested = _first_named_cover(files)
            if nested is not None:
                return nested
            nested_images.extend(
                path for path in files
                if path.suffix.casefold() in COVER_EXTENSIONS
                and not path.is_symlink() and path.is_file()
            )
    except OSError:
        return None
    signalled = sorted(
        (path for path in nested_images if _path_signals_cover(path, album)),
        key=lambda path: (len(path.relative_to(album).parts), str(path).casefold()),
    )
    if signalled:
        return signalled[0]

    ranked = [
        (rank, path) for path in nested_images
        if (rank := _visual_cover_rank(path, album)) is not None
    ]
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1] if ranked else None
