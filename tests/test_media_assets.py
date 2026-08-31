from pathlib import Path

import pytest

from core.media_assets import find_local_cover, is_cover_filename

pytestmark = pytest.mark.portable


def test_find_local_cover_recurses_for_dlsite_main_image(tmp_path: Path) -> None:
    album = tmp_path / "RJ01234567"
    cover = album / "images" / "RJ01234567_img_main.jpg"
    cover.parent.mkdir(parents=True)
    cover.write_bytes(b"image")
    (album / "images" / "scene01.jpg").write_bytes(b"scene")

    assert find_local_cover(album) == cover


def test_single_root_image_is_used_as_cover(tmp_path: Path) -> None:
    album = tmp_path / "RJ01234567"
    album.mkdir()
    image = album / "RJ01234567.jpg"
    image.write_bytes(b"image")

    assert find_local_cover(album) == image


def test_multiple_unnamed_images_do_not_guess(tmp_path: Path) -> None:
    album = tmp_path / "RJ01234567"
    album.mkdir()
    (album / "scene01.jpg").write_bytes(b"one")
    (album / "scene02.jpg").write_bytes(b"two")

    assert find_local_cover(album) is None
    assert is_cover_filename("scene01.jpg") is False
