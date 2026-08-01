from pathlib import Path
from types import SimpleNamespace

import ui.views.library_view as library_module
from ui.views.library_view import LibraryView, open_folder


class FakeDb:
    def __init__(self):
        self.page_calls = []

    def get_library_page(self, **kwargs):
        self.page_calls.append(kwargs)
        return {
            "items": [],
            "total": 0,
            "works_count": 3,
            "summary": {
                "total_works": 2,
                "total_files": 9,
                "total_size": 1000,
                "with_warnings": 1,
            },
        }

    def get_library_diagnostic_rows(self):
        return {
            "works": [],
            "library_items": [],
            "works_count": 3,
            "summary": {"total_works": 2, "total_files": 9, "total_size": 1000, "with_warnings": 1},
        }


class FakeController:
    def __init__(self, tmp_path: Path):
        self.db = FakeDb()
        self.config = SimpleNamespace(
            output_dir=tmp_path / "Downloads",
            library_paths=[str(tmp_path / "Library")],
        )
        self.snacks = []

    def run_blocking(self, function, on_success, **_kwargs):
        on_success(function())

    def show_snack(self, message):
        self.snacks.append(message)


def test_library_search_is_forwarded_to_database(tmp_path: Path) -> None:
    controller = FakeController(tmp_path)
    view = LibraryView(controller)
    view.search_input.value = "RJ00000042"
    view.on_search()
    assert controller.db.page_calls[-1]["search"] == "RJ00000042"
    assert "搜索“RJ00000042”" in view.page_info.value


def test_library_summary_is_dynamic(tmp_path: Path) -> None:
    view = LibraryView(FakeController(tmp_path))
    view.load_library()
    assert "下载器记录 3" in view.summary_bar.value
    assert "已索引 2" in view.summary_bar.value
    assert "磁盘扫描" not in view.summary_bar.value


def test_search_change_does_not_reload_for_each_nonempty_keystroke(tmp_path: Path) -> None:
    controller = FakeController(tmp_path)
    view = LibraryView(controller)
    initial = len(controller.db.page_calls)
    view.search_input.value = "R"
    view._on_search_change()
    assert len(controller.db.page_calls) == initial
    view.search_input.value = ""
    view._on_search_change()
    assert len(controller.db.page_calls) == initial + 1


def test_open_folder_reports_missing_path(tmp_path: Path) -> None:
    ok, message = open_folder(tmp_path / "missing")
    assert not ok
    assert "目录不存在" in message


def test_open_folder_uses_platform_command(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "folder"
    target.mkdir()
    calls = []
    monkeypatch.setattr(library_module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        library_module.subprocess,
        "run",
        lambda args, check: calls.append((args, check)),
    )
    ok, _message = open_folder(target)
    assert ok
    assert calls == [(["xdg-open", str(target)], True)]


def test_library_vault_page_search_and_cover_join(tmp_path: Path) -> None:
    from core.database import LibraryVault
    import json
    from datetime import datetime

    db_path = tmp_path / "history.db"
    with LibraryVault(db_path) as vault:
        vault.execute_write(
            "INSERT INTO works (rj_id, title, local_path, status) VALUES (?, ?, ?, ?)",
            ("RJ00000042", "Needle", str(tmp_path / "Needle"), "completed"),
        )
        vault.execute_write(
            """INSERT INTO library_items
               (rj_id, folder_path, folder_name, total_files, total_size,
                audio_count, has_audio, has_cover, warnings_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("RJ00000042", str(tmp_path / "Needle"), "Needle Folder", 3, 1234, 2, 1, 0, "[]"),
        )
        vault.execute_write(
            """INSERT INTO metadata_cache
               (rj_id, title, circle, cover_url, metadata_json, tracks_json,
                fetched_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("RJ00000042", "Needle", "Circle", "https://example.invalid/cover.jpg",
             json.dumps({}), json.dumps([]), datetime.now(), datetime.now()),
        )
        result = vault.get_library_page(search="Needle", offset=0, limit=20)

    assert result["total"] == 1
    assert result["works_count"] == 1
    assert result["items"][0]["rj_id"] == "RJ00000042"
    assert result["items"][0]["metadata_cover_url"] == "https://example.invalid/cover.jpg"


def test_library_file_preview_is_bounded_and_classifies_files(tmp_path: Path) -> None:
    from ui.views.library_view import collect_file_preview

    album = tmp_path / "RJ00000077"
    album.mkdir()
    for index in range(201):
        suffix = ".mp3" if index == 0 else ".txt"
        (album / f"{index:03d}{suffix}").write_bytes(b"x")

    preview = collect_file_preview(str(album), limit=200)

    assert preview["truncated"] is True
    assert len(preview["items"]) == 200
    assert preview["items"][0]["kind"] == "audio"
    assert preview["items"][0]["size"] == 1


def test_library_vault_detail_returns_metadata_snapshot(tmp_path: Path) -> None:
    from core.database import LibraryVault
    import json
    from datetime import datetime

    db_path = tmp_path / "history.db"
    album = tmp_path / "RJ00000088"
    album.mkdir()
    with LibraryVault(db_path) as vault:
        vault.execute_write(
            "INSERT INTO works (rj_id, title, circle, local_path, status) VALUES (?, ?, ?, ?, ?)",
            ("RJ00000088", "Work title", "Work circle", str(album), "completed"),
        )
        vault.execute_write(
            """INSERT INTO library_items
               (rj_id, folder_path, folder_name, total_files, total_size,
                audio_count, has_audio, has_cover, warnings_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("RJ00000088", str(album), "Album folder", 4, 4096, 3, 1, 0, "[]"),
        )
        vault.execute_write(
            """INSERT INTO metadata_cache
               (rj_id, title, circle, cover_url, metadata_json, tracks_json,
                fetched_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("RJ00000088", "Cache title", "Cache circle", "",
             json.dumps({"tags": ["sleep", "roleplay"]}), json.dumps([{"title": "Track"}]),
             datetime.now(), datetime.now()),
        )
        detail = vault.get_library_detail("rj00000088")

    assert detail is not None
    assert detail["metadata_title"] == "Cache title"
    assert detail["metadata_json"]["tags"] == ["sleep", "roleplay"]
    assert detail["tracks_json"] == [{"title": "Track"}]
    assert detail["folder_path"] == str(album)

def test_library_category_and_sort_are_forwarded_to_database(tmp_path: Path) -> None:
    controller = FakeController(tmp_path)
    view = LibraryView(controller)
    view._set_category("audio")
    view.sort_dropdown.value = "name_asc"
    view._set_sort()
    assert controller.db.page_calls[-1]["category"] == "audio"
    assert controller.db.page_calls[-1]["sort"] == "name_asc"


def test_library_vault_page_category_and_sort(tmp_path: Path) -> None:
    from core.database import LibraryVault

    db_path = tmp_path / "history.db"
    with LibraryVault(db_path) as vault:
        vault.execute_write(
            """INSERT INTO library_items
               (rj_id, folder_path, folder_name, total_files, total_size, has_audio, has_cover, warnings_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("RJ00000002", "two", "Zulu", 2, 20, 1, 0, "[]"),
        )
        vault.execute_write(
            """INSERT INTO library_items
               (rj_id, folder_path, folder_name, total_files, total_size, has_audio, has_cover, warnings_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("RJ00000001", "one", "Alpha", 8, 10, 0, 1, '["warning"]'),
        )
        audio = vault.get_library_page(category="audio", sort="name_asc", limit=20)
        warnings = vault.get_library_page(category="warnings", sort="files_desc", limit=20)

    assert [row["rj_id"] for row in audio["items"]] == ["RJ00000002"]
    assert [row["rj_id"] for row in warnings["items"]] == ["RJ00000001"]
