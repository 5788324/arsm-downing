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
        self.navigations = []

    def run_blocking(self, function, on_success, **_kwargs):
        on_success(function())

    def show_snack(self, message):
        self.snacks.append(message)

    def navigate_to_view(self, index):
        self.navigations.append(index)


def test_library_search_is_forwarded_to_database(tmp_path: Path) -> None:
    controller = FakeController(tmp_path)
    view = LibraryView(controller)
    view.search_input.value = "RJ00000042"
    view.on_search()
    assert controller.db.page_calls[-1]["search"] == "RJ00000042"
    assert "搜索“RJ00000042”" in view.page_info.value


def test_empty_library_guides_user_to_settings(tmp_path: Path) -> None:
    controller = FakeController(tmp_path)
    view = LibraryView(controller)
    view.load_library()

    empty = view.grid.controls[0].content
    assert any(getattr(control, "value", "") == "资源库还是空的"
               for control in empty.controls)
    button = next(control for control in empty.controls
                  if getattr(control, "text", "") == "去设置仓库目录")
    button.on_click(None)
    assert controller.navigations == [3]
    assert view.detail_panel.visible is False


def test_library_with_items_shows_detail_panel(tmp_path: Path) -> None:
    view = LibraryView(FakeController(tmp_path))
    view._apply_cards({
        "page": 0,
        "total_pages": 1,
        "total": 1,
        "search": "",
        "category": "all",
        "sort": "size_desc",
        "works_count": 1,
        "summary": {},
        "items": [{
            "rj_id": "RJ00000001",
            "folder_path": str(tmp_path / "RJ00000001"),
            "folder_name": "Sample",
            "total_files": 2,
            "total_size": 10,
            "audio_count": 1,
            "has_audio": True,
            "has_cover": False,
            "warnings": [],
        }],
    })

    assert view.detail_panel.visible is True


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


def test_library_search_keeps_total_past_last_page_and_summary_tracks_external_writes(tmp_path):
    from core.database import LibraryVault

    with LibraryVault(tmp_path / "history.db") as db:
        assert db.get_library_summary()["total_works"] == 0
        first = db.get_library_summary()
        first["total_works"] = 999
        assert db.get_library_summary()["total_works"] == 0
        db.execute_write(
            "INSERT INTO library_items(rj_id,folder_path,folder_name) VALUES(?,?,?)",
            ("RJ00000042", str(tmp_path / "album"), "聲音專輯"),
        )
        assert db.get_library_summary()["total_works"] == 1
        assert db.get_library_page(search="rj00000042")["items"][0]["rj_id"] == "RJ00000042"
        page = db.get_library_page(search="声音专辑", offset=200)
        assert page["total"] == 1 and page["items"] == []


def test_library_search_migrates_legacy_metadata_and_tracks_changes(tmp_path):
    from core.database import LibraryVault

    path = tmp_path / "legacy.db"
    rid = "RJ00000009"
    with LibraryVault(path) as vault:
        vault.conn.execute("INSERT INTO library_items (rj_id, folder_path, folder_name) "
                           "VALUES (?, '', 'Archive')", (rid,))
        vault.set_metadata_cache(rid, "作品", "社團", "", {"vas": [{"name": "寶石"}]}, [])
        for trigger in ("insert", "update", "delete"):
            vault.conn.execute(f"DROP TRIGGER metadata_search_{trigger}")
        vault.conn.execute("DROP TABLE library_metadata_search")

    with LibraryVault.open_read_only(path) as legacy:
        assert legacy.get_library_page(search="宝石")["total"] == 1
    with LibraryVault(path) as upgraded:
        assert upgraded.get_library_page(search="宝石")["total"] == 1
        upgraded.set_metadata_cache(rid, "作品", "社團", "", {"vas": [{"name": "聲音"}]}, [])
        assert upgraded.get_library_page(search="宝石")["total"] == 0
        assert upgraded.get_library_page(search="声音")["total"] == 1
        upgraded.upsert_work_metadata(rid, "作品新版", "社團", "", {"tags": ["奇幻"]})
        assert upgraded.get_library_page(search="奇幻")["total"] == 1
        upgraded.invalidate_cache(rid)
        assert upgraded.get_library_page(search="奇幻")["total"] == 0


def test_cover_thumbnail_uses_disposable_cache_and_respects_pixel_limit(tmp_path, monkeypatch):
    from PIL import Image
    from core.media_assets import get_cover_thumbnail

    source = tmp_path / "cover.png"
    Image.new("RGB", (1200, 600), "navy").save(source)
    original = source.read_bytes()
    thumbnail = get_cover_thumbnail(source)
    assert thumbnail and thumbnail != source
    with Image.open(thumbnail) as image:
        assert image.size == (400, 200)
    assert get_cover_thumbnail(source) == thumbnail
    assert source.read_bytes() == original

    oversized = tmp_path / "oversized.png"
    Image.new("RGB", (1200, 600)).save(oversized)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100_000)
    assert get_cover_thumbnail(oversized) is None


def test_library_renders_cards_before_starting_cover_worker(tmp_path):
    class DeferredController(FakeController):
        def __init__(self, location):
            super().__init__(location)
            self.jobs = []

        def run_blocking(self, function, on_success, **_kwargs):
            self.jobs.append((function, on_success))

    controller = DeferredController(tmp_path)
    view = LibraryView(controller)
    controller.db.get_library_page = lambda **_: {
        "items": [{"rj_id": "RJ00000001", "folder_path": "", "folder_name": "Sample"}],
        "total": 1,
    }
    view.load_library()
    fetch, render = controller.jobs.pop()
    render(fetch())
    slot = view.grid.controls[0].content.controls[0]
    assert slot.content is None

    cover_worker, cover_render = controller.jobs.pop()
    cover_render(cover_worker())
    assert slot.content is not None

def test_library_sorts_by_first_admission_and_saved_release_date(tmp_path):
    from core.database import LibraryVault

    first, second, cloud, unknown = (f"RJ{n:08d}" for n in range(1, 5))
    with LibraryVault(tmp_path / "history.db") as db:
        items = "INSERT INTO library_items (rj_id,folder_path,folder_name,scanned_at) VALUES (?,?,?,?)"
        db.conn.execute("INSERT INTO works (rj_id,local_path,status,downloaded_at) VALUES (?,?,?,?)",
                        (first, "local", "completed", "2024-01-01T00:00:00"))
        db.conn.executemany(items, [
            (first, "local", "Series A", "2026-11-20"), (second, "local", "Series B", "2025-02-01"),
            (cloud, "", "Series C", None), (unknown, "", "Series D", None),
        ])
        db.conn.execute("INSERT INTO cloud_archives (rj_id,archived_at,updated_at,metadata_json) "
                        "VALUES (?, '2024-06-01','2026-01-01',?)", (cloud, '{"release":"2026-01-01"}'))
        db.set_metadata_cache(first, "First", "", "", {"release": "2025-02-01"}, [])
        db.set_metadata_cache(second, "Second", "", "", {"release_date": "2025-01-01"}, [])
        db.set_metadata_cache(unknown, "Unknown", "", "", {"release": "2026-02-31"}, [])
        db.set_metadata_cache(cloud, "Cloud", "", "", {"release_date": ""}, [])

        def order(sort, **kwargs):
            result = db.get_library_page(sort=sort, **kwargs)
            assert "error" not in result
            return [item["rj_id"] for item in result["items"]]

        assert order("admitted_desc") == [second, cloud, first, unknown]
        assert order("release_desc", search="Series", offset=1, limit=2) == [first, second]
        assert order("release_desc") == [cloud, first, second, unknown]
        db.conn.execute("DELETE FROM library_items WHERE rj_id=?", (first,))
        db.conn.execute(items, (first, "local", "Series A", "2026-11-22"))
        assert order("admitted_desc", search="Series") == [second, cloud, first, unknown]
        db.upsert_work_metadata(unknown, "Updated", "", "", {"release": "2026-11-22"})
        assert order("release_desc") == [unknown, cloud, first, second]
        db.invalidate_cache(unknown)
        assert order("release_desc") == [cloud, first, second, unknown]


def test_exact_album_tag_filter_matches_local_and_cloud_tags_and_updates(tmp_path):
    from core.database import LibraryVault

    local, cloud, similar = (f"RJ{i:08d}" for i in range(1, 4))
    with LibraryVault(tmp_path / "history.db") as db:
        db.conn.executemany("INSERT INTO library_items (rj_id,folder_path,folder_name) VALUES (?,'',?)",
                            [(local, "One"), (cloud, "Two"), (similar, "Three")])
        db.set_metadata_cache(local, "One", "", "", {"tags": [{"name": "ASMR"}, "ASMR"]}, [])
        db.set_metadata_cache(similar, "ASMR", "", "", {"tags": ["ASMR drama"]}, [])
        db.set_metadata_cache(cloud, "Two", "", "", {"tags": []}, [])
        db.conn.execute("INSERT INTO cloud_archives (rj_id,archived_at,updated_at,metadata_json) "
                        "VALUES (?,'2026-01-01','2026-01-01',?)",
                        (cloud, '{"tag":{"123":{"name":"ASMR"}}}'))
        page = db.get_library_page(tag="asmr", sort="rj_desc")
        assert [item["rj_id"] for item in page["items"]] == [cloud, local]
        assert db.get_library_page(tag="ASMR", search="Two")["total"] == 1
        assert db.get_library_detail(cloud)["album_tags"] == ["ASMR"]
        db.set_metadata_cache(local, "One", "", "", {"tags": "Relaxation"}, [])
        assert db.get_library_page(tag="ASMR")["total"] == 1
        assert db.get_library_page(tag="Relaxation")["items"][0]["card_tags"] == ["Relaxation"]


def test_clicking_and_clearing_tag_preserves_sort(tmp_path):
    controller = FakeController(tmp_path)
    view = LibraryView(controller)
    view._sort = "release_desc"
    view.search_input.value = "RJ00000001"
    view._tag_button("ASMR").on_click(None)
    assert view.tag_filter.visible
    assert controller.db.page_calls[-1]["tag"] == "ASMR"
    assert controller.db.page_calls[-1]["search"] == ""
    assert controller.db.page_calls[-1]["sort"] == "release_desc"
    view.tag_filter.on_delete(None)
    assert not view.tag_filter.visible
    assert "tag" not in controller.db.page_calls[-1]
