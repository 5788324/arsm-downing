from core.library_diagnostics import (
    classify_library_anomalies,
    flatten_anomaly_groups,
    normalize_path_key,
    path_is_under_roots,
)


def test_path_normalization_is_cross_platform() -> None:
    assert normalize_path_key(r"E:\\arsm\\RJ00000001") == "e:/arsm/rj00000001"
    assert path_is_under_roots(r"E:\arsm\RJ00000001", [r"e:\ARSM"])
    assert not path_is_under_roots(r"E:\arsm-old\RJ00000001", [r"E:\arsm"])


def test_anomalies_use_configured_roots_not_hardcoded_drives() -> None:
    works = [
        {"rj_id": "RJ00000001", "title": "indexed", "status": "completed", "local_path": r"D:\Library\RJ00000001"},
        {"rj_id": "RJ00000002", "title": "not indexed", "status": "completed", "local_path": r"D:\Library\RJ00000002"},
        {"rj_id": "RJ00000003", "title": "outside", "status": "completed", "local_path": r"E:\Other\RJ00000003"},
    ]
    items = [{
        "rj_id": "RJ00000001", "folder_path": r"D:\Library\RJ00000001",
        "total_files": 2, "total_size": 10, "warnings_json": "[]",
    }]
    groups = classify_library_anomalies(
        works,
        items,
        configured_roots=[r"D:\Library"],
        path_exists=lambda _path: True,
    )
    assert [row["rj_id"] for row in groups["configured_root_not_indexed"]] == ["RJ00000002"]
    assert [row["rj_id"] for row in groups["outside_configured_roots"]] == ["RJ00000003"]
    assert not groups["indexed_path_missing"]


def test_anomaly_search_and_multiple_categories() -> None:
    works = [{
        "rj_id": "RJ123456", "title": "Needle Album", "status": "completed",
        "local_path": "/library/RJ123456",
    }]
    items = [{
        "rj_id": "RJ123456", "folder_path": "/library/RJ123456",
        "total_files": 0, "total_size": 0,
        "warnings_json": '["empty_directory", "no_images", "path_mismatch_with_works_local_path"]',
    }]
    groups = classify_library_anomalies(
        works,
        items,
        configured_roots=["/library"],
        path_exists=lambda _path: True,
        search="needle",
    )
    assert len(groups["noncanonical_rj"]) == 1
    assert len(groups["empty_directory"]) == 1
    assert len(groups["no_images"]) == 1
    assert len(groups["path_mismatch"]) == 1
    assert len(flatten_anomaly_groups(groups, "__all__")) == 4


def test_anomaly_search_can_filter_all_results() -> None:
    groups = classify_library_anomalies(
        [{"rj_id": "RJ00000001", "title": "Alpha", "status": "failed", "local_path": "/missing"}],
        [],
        configured_roots=["/library"],
        path_exists=lambda _path: False,
        search="beta",
    )
    assert flatten_anomaly_groups(groups, "__all__") == []
