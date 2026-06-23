"""WorkStatus — single source of truth for download states.

All status checks use this enum. UI normalize_status maps legacy strings here.
"""

from enum import Enum
from typing import List


class WorkStatus(Enum):
    # ── Active / pipeline ──
    PREPARING = "preparing"       # metadata fetch in progress
    PREPARED = "prepared"         # metadata fetched, folder created
    QUEUED = "queued"             # waiting in download queue
    DOWNLOADING = "downloading"   # actively downloading
    PAUSED = "paused"             # user-paused
    RESUMING = "resuming"         # resume in progress

    # ── Terminal ──
    COMPLETED = "completed"       # all tracks downloaded
    REGISTERED = "registered"     # recorded in works library
    PARTIAL = "partial"           # some tracks failed

    # ── Error / special ──
    FAILED = "failed"             # download failed
    METADATA_FAILED = "metadata_failed"  # metadata/proxy failed
    NO_PENDING = "no_pending"     # resume found no pending tracks

    # ── Library-only (not download pipeline) ──
    DUPLICATE = "duplicate"       # already in library_index
    EXTERNAL = "external"         # found via library scan
    VERIFIED = "verified"         # scan + track check passed
    MISSING = "missing"           # directory not found
    INDEXED = "indexed"           # scanned but not enriched

    @property
    def is_active(self) -> bool:
        """Is the work actively in the download pipeline?"""
        return self in (
            WorkStatus.PREPARING, WorkStatus.PREPARED,
            WorkStatus.QUEUED, WorkStatus.DOWNLOADING,
            WorkStatus.RESUMING,
        )

    @property
    def is_pausable(self) -> bool:
        """Can the work be paused?"""
        return self in (
            WorkStatus.QUEUED, WorkStatus.DOWNLOADING,
            WorkStatus.PREPARED,
        )

    @property
    def is_resumable(self) -> bool:
        """Can the work be resumed?"""
        return self in (WorkStatus.QUEUED, WorkStatus.PAUSED)

    @property
    def is_terminal(self) -> bool:
        """Has the work reached a final state?"""
        return self in (
            WorkStatus.COMPLETED, WorkStatus.REGISTERED,
            WorkStatus.VERIFIED, WorkStatus.EXTERNAL,
            WorkStatus.INDEXED,
        )

    @property
    def needs_metadata_retry(self) -> bool:
        """Should UI show 'retry prepare'?"""
        return self in (
            WorkStatus.METADATA_FAILED, WorkStatus.NO_PENDING,
        )

    @property
    def ui_label(self) -> str:
        """Human-readable label."""
        labels = {
            WorkStatus.PREPARING: "准备中...",
            WorkStatus.PREPARED: "已就绪",
            WorkStatus.QUEUED: "队列中",
            WorkStatus.DOWNLOADING: "下载中",
            WorkStatus.PAUSED: "已暂停",
            WorkStatus.RESUMING: "恢复中...",
            WorkStatus.COMPLETED: "已完成",
            WorkStatus.REGISTERED: "已完成",
            WorkStatus.PARTIAL: "部分完成",
            WorkStatus.FAILED: "下载失败",
            WorkStatus.METADATA_FAILED: "元数据失败",
            WorkStatus.NO_PENDING: "无可恢复文件",
            WorkStatus.DUPLICATE: "重复",
            WorkStatus.EXTERNAL: "外部资源",
            WorkStatus.VERIFIED: "已验证",
            WorkStatus.MISSING: "文件缺失",
            WorkStatus.INDEXED: "已索引",
        }
        return labels.get(self, self.value)

    @staticmethod
    def normalize(status: str) -> 'WorkStatus':
        """Map any status string to a WorkStatus enum member."""
        s = status.strip()
        if not s:
            return WorkStatus.QUEUED

        if any(k in s.lower() for k in (
                "metadata_failed", "metadata failed",
                "metadata proxy failed",
                "获取元数据失败", "元数据失败", "元数据代理失败")):
            return WorkStatus.METADATA_FAILED

        if any(k in s.lower() for k in (
                "no pending", "no_pending", "no pending tracks",
                "无可恢复")):
            return WorkStatus.NO_PENDING

        if "重复" in s or "duplicate" in s.lower():
            return WorkStatus.DUPLICATE

        if s.startswith("Failed") or s.startswith("Error") or \
           s in ("failed", "下载失败"):
            return WorkStatus.FAILED

        if s in ("已完成", "Completed", "completed", "registered"):
            return WorkStatus.COMPLETED

        if "Partially completed" in s or "部分完成" in s:
            return WorkStatus.PARTIAL

        if s in ("已暂停", "Paused", "Paused (partial)"):
            return WorkStatus.PAUSED

        if s in ("Preparing", "准备中..."):
            return WorkStatus.PREPARING
        if s in ("Prepared", "Prepared (cached)", "已就绪"):
            return WorkStatus.PREPARED
        if s in ("Queued", "Queued (cached)", "队列中", "队列排队中"):
            return WorkStatus.QUEUED
        if s in ("Downloading", "下载中"):
            return WorkStatus.DOWNLOADING
        if s in ("Resuming...", "恢复中..."):
            return WorkStatus.RESUMING
        if s in ("external", "外部资源"):
            return WorkStatus.EXTERNAL
        if s in ("verified", "已验证"):
            return WorkStatus.VERIFIED
        if s in ("missing", "文件缺失"):
            return WorkStatus.MISSING
        if s in ("indexed", "已索引"):
            return WorkStatus.INDEXED

        return WorkStatus.QUEUED  # default
