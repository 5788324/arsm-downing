from pathlib import Path

import pytest
from PIL import Image

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


def test_cover_inside_named_directory_is_used(tmp_path: Path) -> None:
    album = tmp_path / "RJ01234567"
    cover = album / "封面图片" / "01.jpg"
    cover.parent.mkdir(parents=True)
    cover.write_bytes(b"image")

    assert find_local_cover(album) == cover


def test_visual_fallback_ignores_scene_and_uses_cover_shaped_image(tmp_path: Path) -> None:
    album = tmp_path / "RJ01234567"
    album.mkdir()
    scene = album / "scene" / "001.jpg"
    scene.parent.mkdir()
    Image.new("RGB", (1200, 800)).save(scene)
    candidate = album / "artwork01.jpg"
    Image.new("RGB", (600, 800)).save(candidate)

    assert find_local_cover(album) == candidate
