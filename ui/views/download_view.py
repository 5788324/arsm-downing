import flet as ft
from typing import Dict, Any
from ui.theme import Styles, ACCENT_PRIMARY, ACCENT_SECONDARY, SUCCESS, WARNING, ERROR, BG_SURFACE_LIGHT
import asyncio
import re
import json
import time
from pathlib import Path

RJ_PATTERN = re.compile(r"(?:RJ)?(\d{6,})")
QUEUE_FILE = Path("queue.json")

class DownloadView(ft.Container):
    def __init__(self, app_controller):
        super().__init__()
        self.app_controller = app_controller
        self.expand = True
        
        self.rj_input = ft.TextField(
            label="输入 RJ 号 (例如: RJ01603020)",
            hint_text="粘贴单个或多个RJ号（空格分隔）并按回车...",
            border_color=ACCENT_PRIMARY,
            focused_border_color=SUCCESS,
            border_radius=10,
            expand=True,
            on_submit=self.on_download_submit
        )
        
        self.download_btn = ft.ElevatedButton(
            "下载",
            icon=ft.icons.DOWNLOAD,
            style=ft.ButtonStyle(
                bgcolor=ACCENT_PRIMARY,
                color="white",
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.padding.all(20)
            ),
            on_click=self.on_download_submit
        )

        self.file_picker = ft.FilePicker(on_result=self.on_file_selected)
        self.batch_btn = ft.ElevatedButton(
            "批量导入文件",
            icon=ft.icons.FOLDER_OPEN,
            style=ft.ButtonStyle(
                bgcolor=BG_SURFACE_LIGHT,
                color="white",
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.padding.all(20)
            ),
            on_click=lambda _: self.file_picker.pick_files(allowed_extensions=["txt"])
        )
        
        self.queue_list = ft.ListView(expand=True, spacing=10)
        
        self.active_downloads: Dict[str, Dict[str, Any]] = {}
        
        self.content = ft.Column([
            self.file_picker,
            ft.Text("下载中心", size=32, weight=ft.FontWeight.BOLD),
            ft.Row([self.rj_input, self.download_btn, self.batch_btn], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Divider(height=20, color="transparent"),
            ft.Text("当前下载队列", size=20, weight=ft.FontWeight.W_500, color=ACCENT_PRIMARY),
            self.queue_list
        ])

        self.load_queue()

    def save_queue(self):
        try:
            dump_data = {}
            for rj, data in self.active_downloads.items():
                dump_data[rj] = {
                    "status": data["status"],
                    "tracks": data.get("tracks", {})
                }
            with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                json.dump(dump_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def load_queue(self):
        if QUEUE_FILE.exists():
            try:
                with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                for rj, data in saved.items():
                    try:
                        # Normalize: ensure RJ prefix for backward compatibility
                        rj_id = f"RJ{rj}" if not rj.upper().startswith("RJ") else rj

                        if data["status"] == "已完成":
                            continue  # Do not load completed tasks, they auto-clear on restart

                        self.active_downloads[rj_id] = {
                            "status": "队列中",
                            "tracks": data.get("tracks", {}),
                            "control": None,
                            "last_time": time.time(),
                            "last_bytes": 0
                        }
                        self.build_queue_item(rj_id)
                        self.app_controller.start_download(rj_id)
                    except Exception as e:
                        print(f"Error loading {rj}: {e}")
            except Exception as e:
                print(f"Failed to load queue: {e}")

    def process_input(self, text: str):
        codes = []
        for match in RJ_PATTERN.finditer(text):
            code = match.group(1)
            if code and code not in codes:
                codes.append(code)

        for rj_num in codes:
            rj_id = f"RJ{rj_num}"  # normalize to full RJ format
            if rj_id not in self.active_downloads or self.active_downloads[rj_id]["status"] == "已完成":
                self.active_downloads[rj_id] = {
                    "status": "队列中",
                    "tracks": {},
                    "control": None,
                    "last_time": time.time(),
                    "last_bytes": 0
                }
                self.build_queue_item(rj_id)
                self.app_controller.start_download(rj_id)
        self.save_queue()

    def on_download_submit(self, e):
        val = self.rj_input.value.strip()
        if not val:
            return
        self.rj_input.value = ""
        self.rj_input.update()
        self.process_input(val)

    def on_file_selected(self, e: ft.FilePickerResultEvent):
        if not e.files:
            return
        file_path = e.files[0].path
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.process_input(content)
            self.app_controller.show_snack(f"成功从文件导入任务！")
        except Exception as err:
            self.app_controller.show_snack(f"读取文件失败: {err}")

    def build_queue_item(self, rj_id: str):
        item_data = self.active_downloads[rj_id]
        status = item_data["status"]
        
        title_text = ft.Text(rj_id, weight=ft.FontWeight.BOLD, size=16)
        status_text = ft.Text(status, color=WARNING, size=12)
        speed_text = ft.Text("", color=ACCENT_SECONDARY, size=12)
        
        # Calculate initial progress
        total = sum(t.get("total", 0) for t in item_data.get("tracks", {}).values())
        down = sum(t.get("downloaded", 0) for t in item_data.get("tracks", {}).values())
        prog = down / total if total > 0 else None
        if status == "已完成": prog = 1.0
        
        prog_bar = ft.ProgressBar(value=prog, color=SUCCESS if prog == 1.0 else ACCENT_PRIMARY)
        
        btn_pause = ft.IconButton(
            icon=ft.icons.PLAY_ARROW if status in ["已暂停", "Paused"] else ft.icons.PAUSE,
            icon_color=ACCENT_PRIMARY,
            tooltip="继续" if status in ["已暂停", "Paused"] else "暂停",
            on_click=lambda e, r=rj_id: self.toggle_pause(r)
        )
        
        btn_cancel = ft.IconButton(
            icon=ft.icons.DELETE_OUTLINE if status == "已完成" else ft.icons.CANCEL,
            icon_color=ERROR,
            tooltip="清除记录" if status == "已完成" else "取消下载",
            on_click=lambda e, r=rj_id: self.cancel_item(r)
        )
        
        actions_row = ft.Row([btn_pause, btn_cancel], spacing=0, alignment=ft.MainAxisAlignment.END)
        if status == "已完成":
            btn_pause.visible = False
            
        actions = ft.Container(content=actions_row, width=90)
        
        tile = ft.ListTile(
            leading=ft.Icon(ft.icons.CLOUD_DOWNLOAD, color=ACCENT_PRIMARY, size=40),
            title=title_text,
            subtitle=ft.Column([
                ft.Row([status_text, speed_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), 
                prog_bar
            ], spacing=5),
            trailing=actions,
            on_click=lambda e, r=rj_id: self.show_detailed_progress(r)
        )
        
        container = Styles.glass_container(tile, padding=10)
        item_data["control"] = container
        item_data["title_text"] = title_text
        item_data["status_text"] = status_text
        item_data["speed_text"] = speed_text
        item_data["prog_bar"] = prog_bar
        item_data["btn_pause"] = btn_pause
        item_data["btn_cancel"] = btn_cancel
        
        # Update existing control if exists
        existing_controls = [c for c in self.queue_list.controls if getattr(c, 'data', None) == rj_id]
        if existing_controls:
            idx = self.queue_list.controls.index(existing_controls[0])
            container.data = rj_id
            self.queue_list.controls[idx] = container
        else:
            container.data = rj_id
            self.queue_list.controls.append(container)
            
        try:
            if self.queue_list.page:
                self.queue_list.update()
        except Exception:
            pass

    def update_work_status(self, rj_id: str, status: str):
        status_map = {
            "Fetching metadata...": "获取元数据中...",
            "Failed to fetch metadata": "获取元数据失败",
            "Fetching track list...": "获取文件列表...",
            "Failed to fetch tracks": "获取文件列表失败",
            "No tracks found": "未找到文件",
            "Queued": "队列排队中",
            "Downloading": "下载中",
            "Completed": "已完成"
        }
        cn_status = status_map.get(status, status)

        if rj_id in self.active_downloads:
            data = self.active_downloads[rj_id]
            data["status"] = cn_status
            if "status_text" in data:
                data["status_text"].value = cn_status
                if status == "Completed":
                    data["status_text"].color = SUCCESS
                    data["prog_bar"].value = 1.0
                    data["prog_bar"].color = SUCCESS
                    data["speed_text"].value = ""
                    if "btn_pause" in data: data["btn_pause"].visible = False
                    if "btn_cancel" in data:
                        data["btn_cancel"].icon = ft.icons.DELETE_OUTLINE
                        data["btn_cancel"].tooltip = "清除记录"
                    self.app_controller.check_achievements()
                elif status.startswith("Failed"):
                    data["status_text"].color = ERROR
                    data["prog_bar"].color = ERROR
                    data["speed_text"].value = ""
                elif status == "Paused":
                    if "btn_pause" in data:
                        data["btn_pause"].icon = ft.icons.PLAY_ARROW
                        data["btn_pause"].tooltip = "继续"
                        data["speed_text"].value = ""
                else:
                    if "btn_pause" in data:
                        data["btn_pause"].icon = ft.icons.PAUSE
                        data["btn_pause"].tooltip = "暂停"
                        data["btn_pause"].visible = True
                        
                try:
                    data["status_text"].update()
                    data["prog_bar"].update()
                    data["speed_text"].update()
                    if "btn_pause" in data: data["btn_pause"].update()
                    if "btn_cancel" in data: data["btn_cancel"].update()
                except Exception:
                    pass
            self.save_queue()

    def toggle_pause(self, rj_id: str):
        data = self.active_downloads.get(rj_id)
        if not data: return
        
        if data["status"] == "已暂停" or data["status"] == "Paused":
            data["status"] = "队列中"
            self.build_queue_item(rj_id)
            self.app_controller.start_download(rj_id)
        else:
            self.app_controller.pause_download(rj_id)
            self.update_work_status(rj_id, "Paused")
            
    def cancel_item(self, rj_id: str):
        data = self.active_downloads.get(rj_id)
        if not data: return
        
        if data["status"] != "已完成":
            self.app_controller.cancel_download(rj_id)
            
        if data.get("control") and data["control"] in self.queue_list.controls:
            self.queue_list.controls.remove(data["control"])
        self.active_downloads.pop(rj_id, None)
        self.queue_list.update()
        self.save_queue()

    def update_track_progress(self, rj_id: str, track_title: str, downloaded: int, total: int, status: str):
        if rj_id not in self.active_downloads:
            return
            
        data = self.active_downloads[rj_id]
        if "tracks" not in data:
            data["tracks"] = {}
        
        data["tracks"][track_title] = {
            "downloaded": downloaded,
            "total": total,
            "status": status
        }
        
        total_bytes = sum(t["total"] for t in data["tracks"].values())
        downloaded_bytes = sum(t["downloaded"] for t in data["tracks"].values())
        
        if total_bytes > 0:
            prog = downloaded_bytes / total_bytes
            if "prog_bar" in data:
                data["prog_bar"].value = prog
                
            now = time.time()
            if "last_time" in data and "last_bytes" in data:
                dt = now - data["last_time"]
                db = downloaded_bytes - data["last_bytes"]
                if dt > 1.0:  # Update speed every second
                    if data.get("status") == "下载中" and db >= 0:
                        speed = db / dt / 1024 / 1024
                        if "speed_text" in data:
                            data["speed_text"].value = f"{speed:.2f} MB/s"
                            try:
                                data["speed_text"].update()
                            except Exception:
                                pass
                    elif data.get("status") in ["队列排队中", "队列中"]:
                        if "speed_text" in data:
                            data["speed_text"].value = ""
                            try:
                                data["speed_text"].update()
                            except Exception:
                                pass
                    data["last_time"] = now
                    data["last_bytes"] = downloaded_bytes
            else:
                data["last_time"] = now
                data["last_bytes"] = downloaded_bytes

            try:
                if "prog_bar" in data:
                    data["prog_bar"].update()
            except Exception:
                pass

        if hasattr(self, "current_dialog_rj") and self.current_dialog_rj == rj_id:
            if hasattr(self, "dialog_list"):
                self.refresh_dialog_list(rj_id)
        
        # Save occasionally, maybe not every chunk to save IO, but let's do it every 5s
        if time.time() - getattr(self, "last_save", 0) > 5:
            self.save_queue()
            self.last_save = time.time()

    def show_detailed_progress(self, rj_id: str):
        data = self.active_downloads.get(rj_id)
        if not data:
            return
            
        self.current_dialog_rj = rj_id
        self.dialog_list = ft.ListView(expand=True, spacing=5, height=400)
        self.refresh_dialog_list(rj_id)
        
        dlg = ft.AlertDialog(
            title=ft.Text(f"详细进度 - {rj_id}"),
            content=ft.Container(self.dialog_list, width=600),
            actions=[ft.TextButton("关闭", on_click=lambda e: self.close_dialog(dlg))]
        )
        self.page.dialog = dlg
        dlg.open = True
        self.page.update()

    def refresh_dialog_list(self, rj_id: str):
        data = self.active_downloads.get(rj_id)
        if not data or not hasattr(self, "dialog_list"):
            return
            
        self.dialog_list.controls.clear()
        for title, info in data.get("tracks", {}).items():
            prog = info["downloaded"] / info["total"] if info.get("total", 0) > 0 else 0
            status_color = SUCCESS if info["status"] == "completed" else ERROR if info["status"] == "failed" else ACCENT_SECONDARY
            
            self.dialog_list.controls.append(
                ft.Column([
                    ft.Row([ft.Text(title[:40], size=12), ft.Text(f"{prog*100:.1f}%", size=12)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.ProgressBar(value=prog, color=status_color)
                ])
            )
        try:
            self.dialog_list.update()
        except Exception:
            pass

    def close_dialog(self, dlg):
        dlg.open = False
        self.current_dialog_rj = None
        self.page.update()
