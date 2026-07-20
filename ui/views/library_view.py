"""P6 Library View — cards + anomaly with filter chips."""
import json, os, platform, subprocess
from pathlib import Path
import flet as ft
from ui.theme import Styles, ACCENT_PRIMARY, SUCCESS, WARNING, ERROR, BG_SURFACE_LIGHT

LIBRARY_PAGE_SIZE = 20
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

ANOMALY_FILTERS = [
    ("__all__", "全部异常"),
    ("on_target_but_not_indexed", "E盘未索引"),
    ("old_library_root_C", "旧库路径"),
    ("path_missing", "路径丢失"),
    ("empty_directory", "空目录"),
    ("no_images", "无图片"),
    ("path_mismatch", "路径不匹配"),
    ("fake_or_legacy", "假RJ/别名"),
]

class LibraryView(ft.Container):
    def __init__(self, app_controller):
        super().__init__()
        self.app_controller = app_controller
        self.expand = True; self.padding = 10
        self._current_page = 0
        self._mode = "cards"
        self._anomaly_filter = "__all__"

        self.search_input = ft.TextField(hint_text="搜索 RJ / 文件夹...", border_radius=10,
            expand=True, on_change=self.on_search, on_submit=self.on_search)
        self.summary_bar = ft.Text("", size=12, color="grey")
        self.page_info = ft.Text("", size=12, color="grey")
        self.btn_prev = ft.TextButton(content=ft.Text("上一页", color=ACCENT_PRIMARY), on_click=lambda e: self._go_page(-1))
        self.btn_next = ft.TextButton(content=ft.Text("下一页", color=ACCENT_PRIMARY), on_click=lambda e: self._go_page(1))
        self.mode_toggle = ft.Row([], spacing=6)
        self.anomaly_chips = ft.Row([], spacing=4, wrap=True)

        self.grid = ft.GridView(expand=True, max_extent=260, child_aspect_ratio=0.72, spacing=12, run_spacing=12)
        self.anomaly_list = ft.ListView(expand=True, spacing=4)

        self.content = ft.Column([
            ft.Text("资源库", size=28, weight=ft.FontWeight.BOLD),
            self.summary_bar,
            ft.Row([self.search_input], spacing=10),
            self.mode_toggle,
            self.anomaly_chips,
            ft.Row([ft.Text("", expand=True), self.page_info, self.btn_prev, self.btn_next],
                alignment=ft.MainAxisAlignment.END),
            ft.Divider(height=1, color="transparent"),
            self.grid,
            self.anomaly_list,
        ], expand=True, spacing=8)

    def _build_mode_toggle(self):
        self.mode_toggle.controls.clear()
        for k, lbl in [("cards", "索引视图"), ("anomalies", "异常视图")]:
            active = self._mode == k
            c = ft.Chip(label=ft.Text(lbl, size=12, color="white"),
                bgcolor=ACCENT_PRIMARY if active else None,
                shape=ft.RoundedRectangleBorder(radius=10),
                on_click=lambda e, key=k: self._set_mode(key))
            self.mode_toggle.controls.append(c)

    def _set_mode(self, mode):
        self._mode = mode; self._current_page = 0; self.load_library()

    def on_search(self, e=None): self._current_page = 0; self.load_library()
    def _go_page(self, delta):
        n = self._current_page + delta
        if n < 0: return
        self._current_page = n; self.load_library()

    def load_library(self):
        self._build_mode_toggle()
        db = self.app_controller.db
        lib_summary = db.get_library_summary()
        cw = db.conn.execute("SELECT COUNT(*) FROM works").fetchone()[0]
        self.summary_bar.value = (
            f"下载器记录: {cw} | 资源库索引: {lib_summary.get('total_works',0)} | 磁盘扫描: ~227")

        self.grid.controls.clear(); self.anomaly_list.controls.clear()
        self.grid.visible = self._mode == "cards"
        self.anomaly_list.visible = self._mode == "anomalies"
        self.anomaly_chips.visible = self._mode == "anomalies"

        if self._mode == "cards":
            self._build_cards(db, lib_summary)
        else:
            self._build_anomalies(db)

    def _build_cards(self, db, lib_summary):
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
                try: c = db.get_metadata_cache(rj_id)
                except: c = None
                if c and c.get("cover_url"): cover_src = c["cover_url"]
            cw = _cover_widget(cover_src, 180) if cover_src else _no_cover_widget(180)
            badges = [ft.Text(rj_id, weight=ft.FontWeight.BOLD, size=14, color=ACCENT_PRIMARY),
                      ft.Text(f"{total_files}f/{fmt_size(total_size)}", size=11, color="grey")]
            if audio_count > 0:
                badges.append(ft.Container(content=ft.Text(f"{audio_count} 音频", size=9, color="white"),
                    bgcolor=SUCCESS, border_radius=999, padding=ft.padding.symmetric(horizontal=6, vertical=2)))
            if not has_cover:
                badges.append(ft.Container(content=ft.Text("无本地封面", size=9, color="white"),
                    bgcolor=WARNING, border_radius=999, padding=ft.padding.symmetric(horizontal=6, vertical=2)))
            card = ft.Column([cw, ft.Row(badges, wrap=True, spacing=4),
                ft.Text(dn, size=13, weight=ft.FontWeight.W_600, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)], spacing=6)
            c = Styles.glass_container(card, padding=10)
            if folder_path: c.on_click = lambda e, p=folder_path: open_folder(p)
            self.grid.controls.append(c)

    def _build_anomaly_chips(self, groups):
        self.anomaly_chips.controls.clear()
        for key, label in ANOMALY_FILTERS:
            count = sum(len(v) for k, v in groups.items()
                       if key == "__all__" or (key == "fake_or_legacy" and k in ("fake_or_test_rj","legacy_alias_rj"))
                       or k == key)
            active = self._anomaly_filter == key
            chip = ft.Chip(label=ft.Text(f"{label} ({count})", size=11, color="white"),
                bgcolor=ACCENT_PRIMARY if active else None,
                shape=ft.RoundedRectangleBorder(radius=10),
                on_click=lambda e, k=key: self._set_anomaly_filter(k))
            self.anomaly_chips.controls.append(chip)

    def _set_anomaly_filter(self, key):
        self._anomaly_filter = key; self.load_library()

    def _build_anomalies(self, db):
        # Load all data once — avoid per-work queries
        works = {r["rj_id"]: r for r in db.conn.execute("SELECT * FROM works").fetchall()}
        lib_ids = set(r[0] for r in db.conn.execute("SELECT rj_id FROM library_items").fetchall())
        # Batch-load all library_items once
        lib_data = {}
        for r in db.conn.execute("SELECT * FROM library_items").fetchall():
            lib_data[r["rj_id"]] = dict(r)

        groups = {"fake_or_test_rj": [], "legacy_alias_rj": [], "old_library_root_C": [],
                  "on_target_but_not_indexed": [], "path_missing": [], "no_images": [],
                  "empty_directory": [], "path_mismatch": []}
        for rj_id, w in works.items():
            lp = w["local_path"] or ""
            li = lib_data.get(rj_id, {})
            warns = []
            if li:
                try: warns = json.loads(li.get("warnings_json", "[]") or "[]")
                except: pass
            cat = None
            if rj_id in FAKE_RJ: cat = "fake_or_test_rj"
            elif rj_id in ALIAS_RJ: cat = "legacy_alias_rj"
            elif lp and not os.path.exists(lp): cat = "path_missing"
            elif lp and lp.replace("\\","/").startswith("E:/") and rj_id not in lib_ids: cat = "on_target_but_not_indexed"
            elif lp and lp.replace("\\","/").startswith(OLD_ROOT.replace("\\","/")): cat = "old_library_root_C"
            elif "empty_directory" in warns: cat = "empty_directory"
            elif "no_images" in warns: cat = "no_images"
            elif "path_mismatch_with_works_local_path" in warns: cat = "path_mismatch"
            if cat:
                is_e = lp.replace("\\","/").startswith("E:/") if lp else False
                groups[cat].append({
                    "rj_id": rj_id, "title": w.get("title","")[:40],
                    "works_status": w.get("status",""), "local_path": lp,
                    "in_lib": rj_id in lib_ids, "on_E": is_e,
                    "disk_files": li.get("total_files",0), "disk_size": li.get("total_size",0),
                    "warnings": warns, "category": cat,
                })

        # Build filter chips
        self._build_anomaly_chips(groups)

        # Flatten based on filter
        all_items = []
        af = self._anomaly_filter
        if af == "fake_or_legacy":
            all_items = groups.get("fake_or_test_rj", []) + groups.get("legacy_alias_rj", [])
        elif af == "__all__":
            for g in ["on_target_but_not_indexed","old_library_root_C","path_missing","empty_directory","no_images","path_mismatch","fake_or_test_rj","legacy_alias_rj"]:
                all_items.extend(groups.get(g, []))
        else:
            all_items = groups.get(af, [])

        self.page_info.value = f"共 {len(all_items)} 项异常"
        self.btn_prev.disabled = True; self.btn_next.disabled = True

        cat_labels = {"on_target_but_not_indexed": "E盘未索引", "old_library_root_C": "旧库路径",
                      "path_missing": "路径丢失", "empty_directory": "空目录", "no_images": "无图片",
                      "path_mismatch": "路径不匹配", "fake_or_test_rj": "假/测试RJ", "legacy_alias_rj": "别名RJ"}
        last_cat = ""
        for a in all_items[:200]:
            cat_cn = cat_labels.get(a["category"], a["category"])
            if cat_cn != last_cat and af == "__all__":
                last_cat = cat_cn
                cnt = len(groups.get(a["category"], []))
                self.anomaly_list.controls.append(
                    ft.Text(f"── {cat_cn} ({cnt}) ──", size=14, weight=ft.FontWeight.BOLD, color=WARNING))
            reason = a["category"]
            line = (f"  {a['rj_id']} | {a['works_status']} | "
                    f"lib={'Y' if a['in_lib'] else 'N'} | "
                    f"{a['disk_files']}f/{fmt_size(a['disk_size'])} | "
                    f"{reason} | {a['local_path'][:40] if a['local_path'] else 'no path'}")
            self.anomaly_list.controls.append(
                ft.Text(line, size=11, color="white",
                       selectable=True, font_family="Consolas"))

def _resolve_local_cover(fp, hc, rid, db):
    if not fp or not hc: return None
    r = Path(fp)
    if not r.exists(): return None
    for n in COVER_CANDIDATES:
        c = r / n
        if c.exists(): return str(c)
    try:
        for ch in r.iterdir():
            if ch.is_file() and ch.suffix.lower() in {".jpg",".jpeg",".png",".webp"}:
                if "cover" in ch.name.lower() or "package" in ch.name.lower():
                    return str(ch)
    except: pass
    return None
def _cover_widget(src, h=180):
    return ft.Container(height=h, border_radius=14, clip_behavior=ft.ClipBehavior.HARD_EDGE,
        bgcolor=BG_SURFACE_LIGHT, content=ft.Image(src=src, fit=ft.ImageFit.COVER))
def _no_cover_widget(h=180):
    return ft.Container(height=h, border_radius=14, bgcolor=ft.Colors.with_opacity(0.55, BG_SURFACE_LIGHT),
        alignment=ft.alignment.center,
        content=ft.Column([ft.Icon(ft.Icons.IMAGE_NOT_SUPPORTED_OUTLINED, color=WARNING, size=36),
            ft.Text("无封面", size=12, color="grey")], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6))
def _lib_data_get(db, rid):
    try:
        r = db.conn.execute("SELECT * FROM library_items WHERE rj_id=?", (rid,)).fetchone()
        return dict(r) if r else {}
    except: return {}
def open_folder(p):
    pp = Path(p)
    if pp.exists():
        try:
            if platform.system() == "Windows": os.startfile(pp)
            elif platform.system() == "Darwin": subprocess.run(["open", pp])
            else: subprocess.run(["xdg-open", pp])
        except: pass
