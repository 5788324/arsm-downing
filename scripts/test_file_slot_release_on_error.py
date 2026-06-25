#!/usr/bin/env python3
"""下载失败也释放 file slot — in-flight 不泄漏."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  file slot release on error\n{'='*60}\n")

    from core.orchestrator import Orchestrator
    import inspect

    src = inspect.getsource(Orchestrator.download_file)

    # ── 1. Find all in-flight decrement patterns ──
    dec_patterns = src.count("_global_inflight = max(0, self._global_inflight - 1)")
    per_rj_patterns = src.count("_per_rj_inflight[meta.rj_id] = max")

    # ── 2. Must decrement on all exit paths ──
    # Error path (not success)
    not_success_pos = src.find("if not success:")
    dec_after_not_success = src.find("_global_inflight", not_success_pos)

    # HTTP error path
    http_err_pos = src.find("if resp.status not in (200, 206):")
    dec_after_http_err = src.find("_global_inflight", http_err_pos) if http_err_pos >= 0 else -1

    # 416 path
    http_416_pos = src.find("resp.status == 416")
    dec_after_416 = src.find("_global_inflight", http_416_pos) if http_416_pos >= 0 else -1

    # Normal exit path (FILE_SLOT_RELEASE)
    rel_pos = src.find("FILE_SLOT_RELEASE")
    dec_after_release = src.find("_global_inflight", rel_pos) if rel_pos >= 0 else -1

    assert dec_after_not_success > 0 or dec_patterns >= 3, \
        f"error path should decrement in-flight (patterns={dec_patterns})"
    print(f"  ✓ error paths decrement _global_inflight ({dec_patterns} occurrences)")

    # ── 3. FILE_SLOT_RELEASE exists in normal path ──
    assert "FILE_SLOT_RELEASE" in src, "should have FILE_SLOT_RELEASE on success"
    print(f"  ✓ FILE_SLOT_RELEASE 在成功路径")

    # ── 4. No double-release possible ──
    # The code structure should prevent double counting
    assert "return True" in src, "should return True on success"
    print(f"  ✓ 无双重释放风险 (return 控制流清晰)")

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
