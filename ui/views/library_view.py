"""P6 Library UI — card view + anomaly list. Reads library_items + works."""
import json, os, platform, subprocess
from pathlib import Path
import flet as ft
from ui.theme import Styles, ACCENT_PRIMARY, SUCCESS, WARNING, ERROR, BG_SURFACE_LIGHT

LIBRARY_PAGE_SIZE = 40
E_ROOT = r"E:\arsm"
OLD_ROOT = r"C:\Users\YANG\Music\arsm.one"
FAKE_RJ = {"RJ00000000", "RJ00123456"}
ALIAS_RJ = {"RJ00323125", "RJ323125"}
COVER_CANDIDATES = ("cover.jpg", "cover.jpeg", "cover.png", "cover.webp",
                     "main.jpg", "main.png", "package.jpg", "package.png")

def fmt_size(b):
    if b >= 1_000_000_000: return f"{b/1_000_000_000:.1f} GB"
    if b >= 1_000_000: return f"{b/1_000_000:.0f} MB"
    if b >= 1_000: return f"{b/1_000:.0f} KB"
    return f"{b} B"

class LibraryView(ft.Container):
    def __init__(self, app_controller):
        super().__init__()
        self.app_controller = app_controller
        self.expand = True; self.padding = 10
        self._current_page = 0; self._anomaly_group = "__all__"
        self._mode = "cards"  # cards | anomalies

        self.search_input = ft.TextField(hint_text="搜索 RJ / 文件夹...", border_radius=10,
            expand=True, on_change=self.on_search, on_submit=self.on_search)
        self.summary_bar = ft.Text("", size=12, color="grey")
        self.page_info = ft.Text("", size=12, color="grey")
        self.btn_prev = ft.TextButton(content=ft.Text("上一页", color=ACCENT_PRIMARY), on_click=lambda e: self._go_page(-1))
        self.btn_next = ft.TextButton(content=ft.Text("下一页", color=ACCENT_PRIMARY), on_click=lambda e: self._go_page(1))
        self.mode_toggle = ft.Row([], spacing=6)

        self.grid = ft.GridView(expand=True, max_extent=260, child_aspect_ratio=0.72, spacing=12, run_spacing=12)
        self.list_view = ft.ListView(expand=True, spacing=4)

        self.content = ft.Column([
            ft.Text("资源库", size=28, weight=ft.FontWeight.BOLD),
            self.summary_bar,
            ft.Row([self.search_input], spacing=10),
            self.mode_toggle,
            ft.Row([ft.Text("", expand=True), self.page_info, self.btn_prev, self.btn_next],
                alignment=ft.MainAxisAlignment.END),
            ft.Divider(height=1, color="transparent"),
            self.grid,
            self.list_view,
        ], expand=True, spacing=8)

    def _build_mode_toggle(self):
        self.mode_toggle.controls.clear()
        for key, label in [("cards", "卡片"), ("anomalies", "异常")]:
            active = self._mode == key
            chip = ft.Chip(label=ft.Text(label, size=12, color="white"),
                bgcolor=ACCENT_PRIMARY if active else None,
                shape=ft.RoundedRectangleBorder(radius=10),
                on_click=lambda e, k=key: self._set_mode(k))
            self.mode_toggle.controls.append(chip)

    def _set_mode(self, mode):
        self._mode = mode; self._current_page = 0; self.load_library()

    def on_search(self, e=None): self._current_page = 0; self.load_library()
    def _go_page(self, delta):
        n = self._current_page + delta
        if n < 0: return
        self._current_page = n; self.load_library()

    def _is_anomaly(self, rj_id, local_path, warnings):
        if rj_id in FAKE_RJ or rj_id in ALIAS_RJ: return True
        lp = local_path or ""
        if lp and not os.path.exists(lp): return True
        if is_on_e(lp) and rj_id not in self._lib_ids: return True
        if is_old_lib(lp): return True
        if not rj_id in self._lib_ids: return True
        if "empty_directory" in warnings: return True
        if "no_images" in warnings: return True
        if "path_mismatch_with_works_local_path" in warnings: return True
        return False

    def load_library(self):
        self._build_mode_toggle()
        db = self.app_controller.db
        lib_summary = db.get_library_summary()
        self.summary_bar.value = (
            f"共 {lib_summary.get('total_works',0)} 索引 | 音频 {lib_summary.get('with_audio',0)} "
            f"| 封面 {lib_summary.get('with_cover',0)} | 警告 {lib_summary.get('with_warnings',0)}")

        self.grid.controls.clear(); self.list_view.controls.clear()
        self.grid.visible = self._mode == "cards"
        self.list_view.visible = self._mode == "anomalies"

        if self._mode == "cards":
            self._build_cards(db)
        else:
            self._build_anomalies(db)

        try:
            if self.grid.page: self.grid.update()
            if self.list_view.page: self.list_view.update()
            if self.summary_bar.page: self.summary_bar.update()
            if self.page_info.page: self.page_info.update()
            if self.mode_toggle.page: self.mode_toggle.update()
        except: pass

    def _build_cards(self, db):
        items = db.get_library_items(limit=LIBRARY_PAGE_SIZE, offset=self._current_page * LIBRARY_PAGE_SIZE)
        total = db.count_library_items()
        tp = max(1, (total + LIBRARY_PAGE_SIZE - 1) // LIBRARY_PAGE_SIZE)
        self.page_info.value = f"第 {self._current_page+1}/{tp} 页"
        self.btn_prev.disabled = self._current_page == 0
        self.btn_next.disabled = self._current_page + 1 >= tp

        for item in items:
            rj_id = item["rj_id"]
            total_files = item.get("total_files", 0)
            total_size = item.get("total_size", 0)
            audio_count = item.get("audio_count", 0)
            has_cover = item.get("has_cover", 0)
            folder_path = item.get("folder_path", "")
            folder_name = item.get("folder_name", rj_id)
            dn = folder_name if len(folder_name) <= 36 else folder_name[:33] + ".."
            cover_src = _resolve_local_cover(folder_path, has_cover, rj_id, db)
            if not cover_src and folder_path:
                cover_src = _remote_cover_fallback(rj_id, db)
            cover_w = _cover_widget(cover_src, height=180) if cover_src else _no_cover_widget(180)

            badges = [ft.Text(rj_id, weight=ft.FontWeight.BOLD, size=14, color=ACCENT_PRIMARY),
                      ft.Text(f"{total_files}f / {fmt_size(total_size)}", size=11, color="grey")]
            if audio_count > 0:
                badges.append(ft.Container(content=ft.Text(f"{audio_count} 音频", size=9, color="white"),
                    bgcolor=SUCCESS, border_radius=999, padding=ft.padding.symmetric(horizontal=6, vertical=2)))
            if not has_cover:
                badges.append(ft.Container(content=ft.Text("无本地封面", size=9, color="white"),
                    bgcolor=WARNING, border_radius=999, padding=ft.padding.symmetric(horizontal=6, vertical=2)))
            card = ft.Column([cover_w, ft.Row(badges, wrap=True, spacing=4),
                ft.Text(dn, size=13, weight=ft.FontWeight.W_600, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)], spacing=6)
            c = Styles.glass_container(card, padding=10)
            if folder_path: c.on_click = lambda e, p=folder_path: open_folder(p)
            self.grid.controls.append(c)

    def _build_anomalies(self, db):
        # Collect all works, detect anomalies
        works = {r["rj_id"]: r for r in db.conn.execute("SELECT * FROM works").fetchall()}
        lib_ids = set(r[0] for r in db.conn.execute("SELECT rj_id FROM library_items").fetchall())
        self._lib_ids = lib_ids

        groups = {"fake_or_test_rj": [], "legacy_alias_rj": [], "old_library_root_C": [],
                  "on_target_but_not_indexed": [], "path_missing": [], "no_images": [],
                  "empty_directory": [], "path_mismatch": [], "clean": []}

        for rj_id, w in works.items():
            lp = w["local_path"] or ""
            lib = lib_ids
            wjson = lib_data_get(db, rj_id)
            warns = []
            if wjson:
                try: warns = json.loads(wjson.get("warnings_json", "[]") or "[]")
                except: pass

            if rj_id in FAKE_RJ: groups["fake_or_test_rj"].append((rj_id, w, warns, "假/测试RJ"))
            elif rj_id in ALIAS_RJ: groups["legacy_alias_rj"].append((rj_id, w, warns, "别名RJ"))
            elif lp and not os.path.exists(lp): groups["path_missing"].append((rj_id, w, warns, "路径丢失"))
            elif is_on_e(lp) and rj_id not in lib_ids: groups["on_target_but_not_indexed"].append((rj_id, w, warns, "在E盘但未索引"))
            elif is_old_lib(lp): groups["old_library_root_C"].append((rj_id, w, warns, "旧库路径"))
            elif "empty_directory" in warns: groups["empty_directory"].append((rj_id, w, warns, "空目录"))
            elif "no_images" in warns: groups["no_images"].append((rj_id, w, warns, "无图片"))
            elif "path_mismatch_with_works_local_path" in warns: groups["path_mismatch"].append((rj_id, w, warns, "路径不匹配"))
            else: groups["clean"].append((rj_id, w, warns, "正常"))

        # Show all non-clean groups
        all_anomalies = []
        order = ["fake_or_test_rj", "legacy_alias_rj", "path_missing", "on_target_but_not_indexed",
                 "old_library_root_C", "empty_directory", "no_images", "path_mismatch"]
        for cat in order:
            all_anomalies.extend(groups.get(cat, []))

        total = len(all_anomalies)
        self.page_info.value = f"共 {total} 项异常"
        self.btn_prev.disabled = True; self.btn_next.disabled = True

        last_cat = ""
        for rj_id, w, warns, label in all_anomalies[:200]:
            if label != last_cat:
                last_cat = label
                self.list_view.controls.append(ft.Container(
                    content=ft.Text(f"── {label} ({len([x for x in all_anomalies if x[3] == label])}) ──",
                        size=14, weight=ft.FontWeight.BOLD, color=WARNING if "丢失" in label or "缺失" in label else ACCENT_PRIMARY),
                    padding=ft.padding.only(top=8, bottom=4)))
            title = (w.get("title") or rj_id)[:60]
            self.list_view.controls.append(ft.Text(
                f"  {rj_id} | {w.get('status','')} | {fmt_size(w.get('size_bytes',0))} | {title} | {w.get('local_path','')[:50]}",
                size=11, color="grey" if "正常" in label else "white"))

def is_on_e(p): return p and p.replace("\\","/").startswith(E_ROOT.replace("\\","/"))
def is_old_lib(p): return p and p.replace("\\","/").startswith(OLD_ROOT.replace("\\","/"))
def _resolve_local_cover(folder_path, has_cover, rj_id, db):
    if not folder_path or not has_cover: return None
    root = Path(folder_path)
    if not root.exists(): return None
    for name in COVER_CANDIDATES:
        c = root / name
        if c.exists(): return str(c)
    try:
        for child in root.iterdir():
            if child.is_file() and child.suffix.lower() in {".jpg",".jpeg",".png",".webp"}:
                if "cover" in child.name.lower() or "package" in child.name.lower():
                    return str(child)
    except: pass
    return None
def _remote_cover_fallback(rj_id, db):
    try:
        c = db.get_metadata_cache(rj_id)
        if c and c.get("cover_url"): return c["cover_url"]
    except: pass
    return None
def _cover_widget(src, height=180):
    return ft.Container(height=height, border_radius=14,
        clip_behavior=ft.ClipBehavior.HARD_EDGE, bgcolor=BG_SURFACE_LIGHT,
        content=ft.Image(src=src, fit=ft.ImageFit.COVER))
def _no_cover_widget(height=180):
    return ft.Container(height=height, border_radius=14,
        bgcolor=ft.colors.with_opacity(0.55, BG_SURFACE_LIGHT),
        alignment=ft.alignment.center,
        content=ft.Column([ft.Icon(ft.icons.IMAGE_NOT_SUPPORTED_OUTLINED, color=WARNING, size=36),
            ft.Text("无封面", size=12, color="grey")],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6))
def lib_data_get(db, rj_id):
    try:
        r = db.conn.execute("SELECT * FROM library_items WHERE rj_id=?", (rj_id,)).fetchone()
        return dict(r) if r else {}
    except: return {}
def open_folder(path_str):
    p = Path(path_str)
    if p.exists():
        try:
            if platform.system() == "Windows": os.startfile(p)
            elif platform.system() == "Darwin": subprocess.run(["open", p])
            else: subprocess.run(["xdg-open", p])
        except: pass
