import json
import logging
from pathlib import Path

CONFIG_FILE = Path("config.json")
HOSTNAME_MIRRORS = [
    "https://api.asmr-200.com",
    "https://api.asmr.one",
    "https://api.asmr-100.com",
    "https://api.asmr-300.com"
]

class ConfigManager:
    """Manages application configuration."""
    def __init__(self):
        self.output_dir = Path("Downloads")
        self.max_concurrent = 3
        self.proxy = None
        self.proxy_download = False
        self.mirror = HOSTNAME_MIRRORS[0]
        self.tag_audio = True
        self.sort_files = False
        self.dir_template = "RJ{rj_id} {title}"
        self.auth_token = None
        self.timeout = 60
        self.dns = "1.1.1.1"
        self.achievements = []

    @classmethod
    def load(cls) -> 'ConfigManager':
        """Load configuration from file or create default."""
        config = cls()
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    config.output_dir = Path(data.get('output_dir', "Downloads"))
                    config.max_concurrent = int(data.get('max_concurrent', 3))
                    config.proxy = data.get('proxy')
                    config.proxy_download = bool(data.get('proxy_download', False))
                    config.mirror = data.get('mirror', HOSTNAME_MIRRORS[0])
                    config.tag_audio = bool(data.get('tag_audio', True))
                    config.sort_files = bool(data.get('sort_files', False))
                    config.dir_template = data.get('dir_template', "RJ{rj_id} {title}")
                    config.auth_token = data.get('auth_token')
                    config.timeout = int(data.get('timeout', 60))
                    config.dns = data.get('dns', '1.1.1.1')
                    config.achievements = data.get('achievements', [])
                    
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logging.warning(f"Config load error: {e}, using defaults")
        return config

    def save(self) -> None:
        """Save configuration to file."""
        data = {
            "output_dir": str(self.output_dir),
            "max_concurrent": self.max_concurrent,
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
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except IOError as e:
            logging.error(f"Failed to save config: {e}")
