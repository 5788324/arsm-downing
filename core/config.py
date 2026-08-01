import json
import logging
import os
from pathlib import Path
from typing import Optional

from core.paths import app_path, resource_path, resolve_runtime_path

CONFIG_FILE: Optional[Path] = None
CONFIG_EXAMPLE_FILE: Optional[Path] = None
_replace_file = os.replace


def _config_file() -> Path:
    return CONFIG_FILE if CONFIG_FILE is not None else app_path("config.json")


def _config_example_file() -> Path:
    return (
        CONFIG_EXAMPLE_FILE
        if CONFIG_EXAMPLE_FILE is not None
        else resource_path("config.example.json")
    )
HOSTNAME_MIRRORS = [
    "https://api.asmr-200.com",
    "https://api.asmr.one",
    "https://api.asmr-100.com",
    "https://api.asmr-300.com"
]


class ConfigManager:
    """Manages application configuration with per-type proxy support."""

    def __init__(self):
        # ── Paths ──
        self.output_dir = app_path("Downloads")
        self.library_paths: list = []  # P3.3: extra library scan paths
        self.external_intake_root: Optional[str] = None
        self.external_quarantine_root: Optional[str] = None
        self.max_concurrent = 3   # legacy, maps to file_concurrency

        # ── Download concurrency (P2) ──
        self.work_concurrency: int = 1
        self.metadata_concurrency: int = 2
        self.file_concurrency: int = 4
        self.auto_resume_on_start: bool = False  # RC7.9: default OFF
        self.chunk_size: int = 1048576  # 1 MB
        self.retry_count: int = 5
        self.retry_backoff: int = 2    # exponential base seconds

        # ── Proxy: three-channel split ──
        self.metadata_proxy: Optional[str] = None   # API metadata requests
        self.download_proxy: Optional[str] = None   # Audio file downloads
        self.cover_proxy: Optional[str] = None      # Cover image downloads
        self.download_fallback_to_proxy: bool = False  # RC7.5: default OFF

        # ── Legacy (kept for backward compat, maps to metadata_proxy) ──
        self.proxy: Optional[str] = None
        self.proxy_download: bool = False

        # ── API ──
        self.mirror = HOSTNAME_MIRRORS[0]
        self.auth_token: Optional[str] = None
        self.timeout = 60
        self.dns = "1.1.1.1"

        # ── Features ──
        self.tag_audio = True
        self.sort_files = False
        self.dir_template = "{rj_id} {title}"

        # ── Game-ish ──
        self.achievements: list = []

    # ── Proxy helpers ──
    def get_proxy_for(self, purpose: str) -> Optional[str]:
        """Return the correct proxy for a request purpose.

        Args:
            purpose: 'metadata', 'download', or 'cover'
        """
        if purpose == 'metadata':
            return self.metadata_proxy or self.proxy
        elif purpose == 'download':
            if self.download_proxy:
                return self.download_proxy
            if self.proxy_download:
                return self.proxy
            return None
        elif purpose == 'cover':
            return self.cover_proxy or self.metadata_proxy or self.proxy
        return None

    @classmethod
    def load(cls) -> 'ConfigManager':
        """Load configuration from file or create default."""
        import shutil
        config_file = _config_file()
        example_file = _config_example_file()
        if not config_file.exists() and example_file.exists():
            config_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(example_file, config_file)
        config = cls()
        if config_file.exists():
            try:
                with config_file.open('r', encoding='utf-8') as f:
                    data = json.load(f)

                config.output_dir = resolve_runtime_path(
                    data.get('output_dir', 'Downloads'))
                config.library_paths = [
                    str(resolve_runtime_path(value))
                    for value in data.get('library_paths', [])
                    if str(value).strip()
                ]
                config.external_intake_root = data.get('external_intake_root')
                config.external_quarantine_root = data.get('external_quarantine_root')
                config.max_concurrent = int(
                    data.get('max_concurrent', 3))
                config.work_concurrency = max(1, min(int(
                    data.get('work_concurrency', 1)), 4))
                config.metadata_concurrency = max(1, min(int(
                    data.get('metadata_concurrency', 2)), 8))
                config.file_concurrency = max(1, min(int(
                    data.get('file_concurrency', 4)), 16))
                config.chunk_size = int(
                    data.get('chunk_size', 1048576))
                config.retry_count = int(
                    data.get('retry_count', 5))
                config.retry_backoff = int(
                    data.get('retry_backoff', 2))
                config.tag_audio = bool(
                    data.get('tag_audio', True))
                config.sort_files = bool(
                    data.get('sort_files', False))
                config.mirror = data.get(
                    'mirror', HOSTNAME_MIRRORS[0])
                config.dir_template = data.get(
                    'dir_template', '{rj_id} {title}')
                config.auth_token = data.get('auth_token')
                config.timeout = int(data.get('timeout', 60))
                config.dns = data.get('dns', '1.1.1.1')
                config.achievements = data.get('achievements', [])

                # ── Proxy: new three-channel, fall back to legacy ──
                config.metadata_proxy = data.get('metadata_proxy')
                config.download_proxy = data.get('download_proxy')
                config.cover_proxy = data.get('cover_proxy')
                config.download_fallback_to_proxy = bool(
                    data.get('download_fallback_to_proxy', False))  # RC7.5: default OFF

                # Legacy compat
                config.proxy = data.get('proxy')
                config.proxy_download = bool(
                    data.get('proxy_download', False))

                # Auto-promote: if old proxy is set but new ones aren't
                if config.proxy and not config.metadata_proxy:
                    config.metadata_proxy = config.proxy
                if config.proxy_download and not config.download_proxy:
                    config.download_proxy = config.proxy

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logging.warning(f"Config load error: {e}, using defaults")
        return config

    def save(self) -> None:
        """Save configuration to file."""
        data = {
            "output_dir": str(self.output_dir),
            "library_paths": self.library_paths,
            "external_intake_root": self.external_intake_root,
            "external_quarantine_root": self.external_quarantine_root,
            "max_concurrent": self.max_concurrent,
            "work_concurrency": self.work_concurrency,
            "metadata_concurrency": self.metadata_concurrency,
            "file_concurrency": self.file_concurrency,
            "chunk_size": self.chunk_size,
            "retry_count": self.retry_count,
            "retry_backoff": self.retry_backoff,
            "metadata_proxy": self.metadata_proxy,
            "download_proxy": self.download_proxy,
            "cover_proxy": self.cover_proxy,
            "download_fallback_to_proxy": self.download_fallback_to_proxy,
            "proxy": self.proxy,
            "proxy_download": self.proxy_download,
            "mirror": self.mirror,
            "tag_audio": self.tag_audio,
            "sort_files": self.sort_files,
            "dir_template": self.dir_template,
            "auth_token": self.auth_token,
            "timeout": self.timeout,
            "dns": self.dns,
            "achievements": self.achievements
        }
        config_file = _config_file()
        temp_file = config_file.with_suffix(config_file.suffix + ".tmp")
        try:
            config_file.parent.mkdir(parents=True, exist_ok=True)
            with temp_file.open('w', encoding='utf-8', newline='\n') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            _replace_file(temp_file, config_file)
        except OSError as e:
            logging.error(f"Failed to save config: {e}")
            try:
                temp_file.unlink(missing_ok=True)
            except OSError:
                pass
            raise
