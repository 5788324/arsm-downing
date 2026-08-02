"""Validation helpers for settings that must fail closed before persistence."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

_ALLOWED_PROXY_SCHEMES = {"http", "https"}


def validate_proxy_uri(value: str | None) -> str | None:
    """Return a normalized proxy URI or ``None`` for a disabled proxy.

    ARSM Suite currently delegates proxy transport to aiohttp.  The settings
    layer therefore accepts only explicit HTTP(S) proxy URIs and rejects path,
    query and fragment components that are commonly caused by pasted web URLs.
    """
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        parsed = urlsplit(normalized)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"代理地址端口无效: {exc}") from exc
    if parsed.scheme.lower() not in _ALLOWED_PROXY_SCHEMES:
        raise ValueError("代理地址仅支持 http:// 或 https://")
    if not parsed.hostname:
        raise ValueError("代理地址缺少主机名")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("代理端口必须位于 1-65535")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("代理地址不能包含路径、查询参数或片段")
    # urlsplit lower-cases hostname only when read; preserve credentials and the
    # user's original spelling while trimming a harmless trailing slash.
    return normalized[:-1] if normalized.endswith("/") else normalized


def validate_writable_directory(value: str | os.PathLike[str]) -> Path:
    """Resolve/create a directory and verify current-user write access."""
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("下载保存目录不能为空")
    path = Path(raw).expanduser().resolve(strict=False)
    existed = path.exists()
    if existed and not path.is_dir():
        raise ValueError(f"路径不是目录: {path}")
    try:
        path.mkdir(parents=True, exist_ok=True)
        fd, probe = tempfile.mkstemp(prefix=".arsm-write-test-", dir=str(path))
        try:
            os.write(fd, b"ARSM")
            os.fsync(fd)
        finally:
            os.close(fd)
            try:
                os.unlink(probe)
            except FileNotFoundError:
                pass
    except OSError as exc:
        if not existed:
            try:
                path.rmdir()
            except OSError:
                pass
        raise ValueError(f"目录不可写: {path} ({exc})") from exc
    return path


def normalize_library_paths(values) -> list[str]:
    """Normalize, validate and de-duplicate read-only library roots."""
    result: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        raw = str(value or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser().resolve(strict=False)
        if path.exists() and not path.is_dir():
            raise ValueError(f"仓库路径不是目录: {path}")
        key = os.path.normcase(os.path.normpath(str(path)))
        if key in seen:
            continue
        seen.add(key)
        result.append(str(path))
    return result
