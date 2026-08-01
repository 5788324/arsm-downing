"""Windows system-tray adapter.  It is deliberately optional and UI-agnostic."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger("arsm.tray")


class SystemTray:
    """Own a small pystray icon and forward menu actions to the UI queue.

    Importing or starting the tray is optional: a missing desktop backend must
    never prevent the downloader from performing its normal graceful shutdown.
    """

    def __init__(
        self,
        *,
        on_show: Callable[[], None],
        on_pause_all: Callable[[], None],
        on_resume_all: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        self._on_show = on_show
        self._on_pause_all = on_pause_all
        self._on_resume_all = on_resume_all
        self._on_exit = on_exit
        self._icon = None
        self._thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        return self._icon is not None

    def start(self) -> bool:
        """Create a detached tray icon; return False when unavailable."""
        if self._icon is not None:
            return True
        try:
            import pystray
            from PIL import Image, ImageDraw

            image = Image.new("RGBA", (64, 64), (19, 28, 47, 255))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((8, 8, 56, 56), radius=14, fill=(97, 73, 197, 255))
            draw.polygon(((25, 21), (47, 32), (25, 43)), fill=(255, 255, 255, 255))
            self._icon = pystray.Icon(
                "ARSM-Suite",
                image,
                "ARSM Suite",
                menu=pystray.Menu(
                    pystray.MenuItem("打开窗口", lambda *_: self._on_show(), default=True),
                    pystray.MenuItem("全部暂停", lambda *_: self._on_pause_all()),
                    pystray.MenuItem("全部继续", lambda *_: self._on_resume_all()),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("彻底退出", lambda *_: self._on_exit()),
                ),
            )
            self._thread = threading.Thread(target=self._icon.run, name="arsm-system-tray", daemon=True)
            self._thread.start()
            return True
        except Exception:
            logger.info("System tray unavailable; window close will exit normally", exc_info=True)
            self._icon = None
            return False

    def stop(self) -> None:
        icon, self._icon = self._icon, None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                logger.debug("Unable to stop system tray", exc_info=True)
