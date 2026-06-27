"""Single source of truth for work and download states."""

from enum import Enum


class WorkStatus(Enum):
    PREPARING = "preparing"
    PREPARED = "prepared"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    RESUMING = "resuming"

    COMPLETED = "completed"
    REGISTERED = "registered"
    PARTIAL = "partial"

    FAILED = "failed"
    METADATA_FAILED = "metadata_failed"
    NO_PENDING = "no_pending"
    STALE = "stale"
    IGNORED = "ignored"

    DUPLICATE = "duplicate"
    EXTERNAL = "external"
    VERIFIED = "verified"
    MISSING = "missing"
    INDEXED = "indexed"

    ALREADY_QUEUED = "already_queued"
    ALREADY_RUNNING = "already_running"

    @property
    def is_active(self) -> bool:
        return self in (
            WorkStatus.PREPARING,
            WorkStatus.PREPARED,
            WorkStatus.QUEUED,
            WorkStatus.DOWNLOADING,
            WorkStatus.RESUMING,
        )

    @property
    def is_pausable(self) -> bool:
        return self in (
            WorkStatus.QUEUED,
            WorkStatus.DOWNLOADING,
            WorkStatus.PREPARED,
        )

    @property
    def is_resumable(self) -> bool:
        return self in (WorkStatus.QUEUED, WorkStatus.PAUSED)

    @property
    def is_terminal(self) -> bool:
        return self in (
            WorkStatus.COMPLETED,
            WorkStatus.REGISTERED,
            WorkStatus.VERIFIED,
            WorkStatus.EXTERNAL,
            WorkStatus.INDEXED,
            WorkStatus.STALE,
            WorkStatus.IGNORED,
        )

    @property
    def needs_metadata_retry(self) -> bool:
        return self in (WorkStatus.METADATA_FAILED, WorkStatus.NO_PENDING)

    @property
    def ui_label(self) -> str:
        labels = {
            WorkStatus.PREPARING: "准备中...",
            WorkStatus.PREPARED: "已就绪",
            WorkStatus.QUEUED: "队列中",
            WorkStatus.DOWNLOADING: "下载中",
            WorkStatus.PAUSED: "已暂停",
            WorkStatus.RESUMING: "恢复中...",
            WorkStatus.COMPLETED: "已完成",
            WorkStatus.REGISTERED: "已登记",
            WorkStatus.PARTIAL: "部分完成",
            WorkStatus.FAILED: "下载失败",
            WorkStatus.METADATA_FAILED: "元数据失败",
            WorkStatus.NO_PENDING: "无可恢复文件",
            WorkStatus.STALE: "历史残留",
            WorkStatus.IGNORED: "已忽略",
            WorkStatus.DUPLICATE: "重复",
            WorkStatus.EXTERNAL: "外部资源",
            WorkStatus.VERIFIED: "已验证",
            WorkStatus.MISSING: "目录缺失",
            WorkStatus.INDEXED: "已入库",
        }
        return labels.get(self, self.value)

    @staticmethod
    def normalize(status: str) -> "WorkStatus":
        s = (status or "").strip()
        if not s:
            return WorkStatus.QUEUED

        s_lower = s.lower()

        if any(k in s_lower for k in (
            "metadata_failed",
            "metadata failed",
            "metadata proxy failed",
        )) or s in (
            "元数据失败",
            "获取元数据失败",
            "获取文件列表失败",
        ):
            return WorkStatus.METADATA_FAILED

        if any(k in s_lower for k in ("no pending", "no_pending", "no pending tracks")) or s in (
            "无可恢复文件",
            "无待下载文件",
        ):
            return WorkStatus.NO_PENDING

        if s in ("stale", "历史残留"):
            return WorkStatus.STALE
        if s in ("ignored", "已忽略"):
            return WorkStatus.IGNORED

        if s in ("重复", "已重复") or "duplicate" in s_lower:
            return WorkStatus.DUPLICATE

        if s.startswith("Failed") or s.startswith("Error") or s in ("failed", "下载失败", "错误") or s.startswith("错误"):
            return WorkStatus.FAILED

        if s in ("已完成", "Completed", "completed"):
            return WorkStatus.COMPLETED
        if s in ("已登记", "registered"):
            return WorkStatus.REGISTERED

        if "Partially completed" in s or s in ("部分完成", "partial"):
            return WorkStatus.PARTIAL

        if s in ("已暂停", "Paused", "Paused (partial)", "paused"):
            return WorkStatus.PAUSED

        if s in ("Preparing", "准备中..."):
            return WorkStatus.PREPARING
        if s in ("Prepared", "Prepared (cached)", "已就绪", "已就绪 [缓存]"):
            return WorkStatus.PREPARED
        if s in ("Queued", "Queued (cached)", "队列中", "队列排队中", "队列排队中 [缓存]"):
            return WorkStatus.QUEUED
        if s in ("Downloading", "下载中"):
            return WorkStatus.DOWNLOADING
        if s in ("Resuming...", "恢复中..."):
            return WorkStatus.RESUMING
        if s in ("external", "外部资源"):
            return WorkStatus.EXTERNAL
        if s in ("verified", "已验证"):
            return WorkStatus.VERIFIED
        if s in ("missing", "目录缺失"):
            return WorkStatus.MISSING
        if s in ("indexed", "已入库"):
            return WorkStatus.INDEXED
        if s == "already_queued":
            return WorkStatus.QUEUED
        if s == "already_running":
            return WorkStatus.DOWNLOADING

        return WorkStatus.QUEUED
