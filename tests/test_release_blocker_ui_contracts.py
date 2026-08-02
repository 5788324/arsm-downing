from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.portable
ROOT = Path(__file__).resolve().parents[1]


def source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def class_node(relative: str, name: str) -> ast.ClassDef:
    tree = ast.parse(source(relative), filename=relative)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"missing class {name} in {relative}")


def method_node(relative: str, class_name: str, method_name: str):
    cls = class_node(relative, class_name)
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name:
            return node
    raise AssertionError(f"missing method {class_name}.{method_name} in {relative}")


def method_names(relative: str, name: str) -> set[str]:
    cls = class_node(relative, name)
    return {
        node.name
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _path(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _path(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _literal(node: ast.AST | None):
    try:
        return ast.literal_eval(node) if node is not None else None
    except (ValueError, TypeError):
        return None


def _callback_path(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Lambda):
        for child in ast.walk(node.body):
            if isinstance(child, ast.Call):
                return _path(child.func)
        return None
    return _path(node)


@dataclass(frozen=True)
class ControlContract:
    control: str
    text: str | None
    label: str | None
    tooltip: str | None
    callback: str | None
    disabled: bool | None


def control_contracts(relative: str, class_name: str) -> list[ControlContract]:
    cls = class_node(relative, class_name)
    result: list[ControlContract] = []
    supported = {"ElevatedButton", "IconButton", "TextButton", "Switch"}
    for node in ast.walk(cls):
        if not isinstance(node, ast.Call):
            continue
        control = (_path(node.func) or "").rsplit(".", 1)[-1]
        if control not in supported:
            continue
        values = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        first = _literal(node.args[0]) if node.args else None
        text = first if isinstance(first, str) else _literal(values.get("text"))
        label = _literal(values.get("label"))
        tooltip = _literal(values.get("tooltip"))
        callback = _callback_path(values.get("on_click") or values.get("on_change"))
        disabled = _literal(values.get("disabled"))
        result.append(ControlContract(
            control=control,
            text=text if isinstance(text, str) else None,
            label=label if isinstance(label, str) else None,
            tooltip=tooltip if isinstance(tooltip, str) else None,
            callback=callback,
            disabled=disabled if isinstance(disabled, bool) else None,
        ))
    return result


def option_contracts(relative: str, class_name: str) -> dict[str, str]:
    cls = class_node(relative, class_name)
    result: dict[str, str] = {}
    for node in ast.walk(cls):
        if not isinstance(node, ast.Call) or (_path(node.func) or "").rsplit(".", 1)[-1] != "Option":
            continue
        values = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        key = _literal(values.get("key"))
        text = _literal(values.get("text"))
        if isinstance(key, str) and isinstance(text, str):
            result[key] = text
    return result


def direct_self_callbacks(relative: str, name: str) -> set[str]:
    """Collect direct ``on_* = self.method`` callback references."""
    cls = class_node(relative, name)
    callbacks: set[str] = set()
    for node in ast.walk(cls):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg not in {"on_click", "on_change", "on_submit", "on_result"}:
                continue
            value = keyword.value
            if (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id == "self"
            ):
                callbacks.add(value.attr)
    return callbacks


def assert_control(
    records: list[ControlContract],
    *,
    control: str,
    callback: str | None,
    text: str | None = None,
    label: str | None = None,
    tooltip: str | None = None,
    disabled: bool | None = None,
) -> None:
    matches = [
        item for item in records
        if item.control == control
        and (callback is None or item.callback == callback)
        and (text is None or item.text == text)
        and (label is None or item.label == label)
        and (tooltip is None or item.tooltip == tooltip)
        and (disabled is None or item.disabled is disabled)
    ]
    assert matches, (
        f"missing control={control!r} text={text!r} label={label!r} "
        f"tooltip={tooltip!r} callback={callback!r} disabled={disabled!r}; "
        f"actual={records!r}"
    )


@pytest.mark.parametrize(
    ("relative", "class_name"),
    [
        ("ui/views/download_view_base.py", "DownloadView"),
        ("ui/views/download_view.py", "DownloadView"),
        ("ui/views/library_view.py", "LibraryView"),
        ("ui/views/settings_view.py", "SettingsView"),
        ("ui/views/tools_view.py", "ToolsView"),
    ],
)
def test_every_direct_ui_callback_resolves_to_a_method(relative, class_name):
    callbacks = direct_self_callbacks(relative, class_name)
    methods = method_names(relative, class_name)
    if relative == "ui/views/download_view.py":
        methods |= method_names("ui/views/download_view_base.py", "DownloadView")
    assert callbacks <= methods, f"unresolved callbacks: {sorted(callbacks - methods)}"


def test_download_center_buttons_use_exact_visible_tooltips_and_callbacks():
    records = control_contracts("ui/views/download_view_base.py", "DownloadView")
    for tooltip, callback in (
        ("重新准备", "self._retry_prepare"),
        ("重试下载", "self._retry_failed"),
        ("继续已取消任务", "self.app_controller.resume_cancelled_download"),
        ("暂停并隐藏（保留断点）", "self.pause_and_hide_item"),
        ("取消任务（保留断点）", "self.cancel_item"),
        ("重连（暂停后重新连接）", "self._reconnect_job"),
    ):
        assert_control(
            records,
            control="IconButton",
            tooltip=tooltip,
            callback=callback,
        )


def test_download_center_filter_and_batch_labels_match_visible_flet_controls():
    options = option_contracts("ui/views/download_view.py", "DownloadView")
    assert options == {
        "working": "活动任务",
        "active": "下载中",
        "queued": "等待中",
        "paused": "已暂停",
        "failed": "失败",
        "completed": "已完成",
        "cancelled": "已取消",
        "all": "全部",
    }
    cls = class_node("ui/views/download_view.py", "DownloadView")
    visible_strings = {
        node.value for node in ast.walk(cls)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert {"批量粘贴", "预览并添加"} <= visible_strings
    methods = method_names("ui/views/download_view.py", "DownloadView")
    assert {"_open_batch_paste_dialog", "process_input"} <= methods
    text = source("ui/views/download_view.py")
    assert "preparing_rj_ids" in text
    assert "resuming_rj_ids" in text


def test_controller_wires_every_download_and_tray_action():
    base = source("ui/app_base.py")
    shell = source("ui/app.py")
    required = {
        "start_download", "pause_download", "resume_download",
        "reconnect_download", "cancel_download", "pause_and_hide_download",
        "resume_cancelled_download", "pause_all_downloads",
        "resume_all_downloads",
    }
    methods = method_names("ui/app_base.py", "AppController")
    methods |= method_names("ui/app.py", "AppController")
    assert required <= methods
    for message in (
        "tray_show_window", "tray_pause_all", "tray_resume_all", "tray_exit",
    ):
        assert message in base
    assert 'stats.get("metadata_required", 0)' in shell
    assert 'stats.get("unrecoverable", 0)' in shell


def test_library_all_modes_search_navigation_and_async_guards_exist():
    text = source("ui/views/library_view.py")
    methods = method_names("ui/views/library_view.py", "LibraryView")
    assert {
        "load_library", "on_search", "clear_search", "_go_page",
        "_set_mode", "_set_category", "_set_sort",
        "_set_anomaly_filter", "select_album", "_open_folder", "_copy_text",
    } <= methods
    assert '(("cards", "索引视图"), ("anomalies", "异常视图"))' in text
    assert "generation != self._load_generation" in text
    assert "generation != self._detail_generation" in text
    assert "not self._active" in text
    assert 'metadata_cover_url") or None' not in text
    assert 'work_cover_url") or None' not in text


def test_settings_page_covers_paths_proxies_fallbacks_and_atomic_rollback():
    text = source("ui/views/settings_view.py")
    for label in (
        "下载保存目录", "仓库目录", "外部资源扫描目录",
        "元数据代理", "封面代理", "下载代理",
        "下载直连失败后回退到代理", "封面代理失败时允许直连回退",
        "保存设置",
    ):
        assert label in text
    for token in (
        "validate_proxy_uri", "validate_writable_directory",
        "normalize_library_paths", "service_previous", "created_output_dir",
        "config.save()",
    ):
        assert token in text
    assert "设置未保存" in text


def _assert_advanced_guard(method_name: str, action: str) -> None:
    method = method_node("ui/views/tools_view.py", "ToolsView", method_name)
    body = list(method.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    assert body and isinstance(body[0], ast.If), f"{method_name} has no leading advanced guard"
    test = body[0].test
    assert isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
    assert isinstance(test.operand, ast.Call)
    assert _path(test.operand.func) == "self._require_advanced"
    assert [_literal(value) for value in test.operand.args] == [action]
    assert body[0].body and isinstance(body[0].body[0], ast.Return)


def test_tools_page_safe_actions_match_real_flet_buttons_and_callbacks():
    records = control_contracts("ui/views/tools_view.py", "ToolsView")
    for text, callback in (
        ("运行一键诊断", "self.run_diagnostic"),
        ("测试网络", "self.test_network"),
        ("扫描仓库", "self.scan_library"),
        ("诊断失败任务", "self.diagnose_failed"),
        ("预览迁移计划", "self.migrate_dry_run"),
        ("验证迁移", "self.verify_migrated"),
        ("预览队列清理", "self.clean_queue"),
        ("扫描计划", "self.external_scan"),
        ("生成完整 DRY-RUN 报告", "self.external_dry_run"),
    ):
        assert_control(
            records,
            control="ElevatedButton",
            text=text,
            callback=callback,
        )
    assert_control(
        records,
        control="Switch",
        label="高级维护模式",
        callback="self._on_advanced_mode_change",
    )


def test_tools_page_mutations_are_guarded_and_external_execution_is_frozen():
    for method_name, action in (
        ("repair_db", "数据库压缩"),
        ("clear_cache", "元数据缓存清理"),
        ("backlog_reenable", "历史状态恢复"),
        ("migrate_execute", "实际资源迁移"),
    ):
        _assert_advanced_guard(method_name, action)

    records = control_contracts("ui/views/tools_view.py", "ToolsView")
    assert_control(
        records,
        control="ElevatedButton",
        text="真实执行已冻结",
        callback=None,
        disabled=True,
    )
    external = method_node("ui/views/tools_view.py", "ToolsView", "external_execute")
    calls = {_path(node.func) for node in ast.walk(external) if isinstance(node, ast.Call)}
    names = {node.id for node in ast.walk(external) if isinstance(node, ast.Name)}
    assert "self.app_controller.show_snack" in calls
    assert "EXECUTION_STOP_MESSAGE" in names


def test_system_tray_has_complete_end_user_menu():
    text = source("core/tray.py")
    for label in ("打开窗口", "全部暂停", "全部继续", "彻底退出"):
        assert label in text
    assert "daemon=True" in text
    assert "System tray unavailable" in text
