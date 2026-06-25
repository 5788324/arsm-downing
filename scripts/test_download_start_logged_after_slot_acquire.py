#!/usr/bin/env python3
"""DOWNLOAD_START 日志必须在 semaphore acquire 后打印."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  DOWNLOAD_START 在 semaphore 内打印\n{'='*60}\n")

    from core.orchestrator import Orchestrator
    import inspect

    src = inspect.getsource(Orchestrator.download_file)

    # ── 1. Find FILE_SLOT_ACQUIRE ──
    acqu_pos = src.find("FILE_SLOT_ACQUIRE")
    assert acqu_pos >= 0, "should have FILE_SLOT_ACQUIRE"
    print(f"  ✓ FILE_SLOT_ACQUIRE 存在")

    # ── 2. Find DOWNLOAD_START ──
    start_pos = src.find("DOWNLOAD_START")
    assert start_pos >= 0, "should have DOWNLOAD_START"

    # ── 3. Find DOWNLOAD_ATTEMPT ──
    attempt_pos = src.find("DOWNLOAD_ATTEMPT")
    assert attempt_pos >= 0, "should have DOWNLOAD_ATTEMPT"

    # ── 4. Find async with file_sem ──
    sem_pos = src.find("async with file_sem")
    assert sem_pos >= 0, "should have async with file_sem"

    # ── 5. FILE_SLOT_ACQUIRE and DOWNLOAD_START must be AFTER async with file_sem ──
    assert acqu_pos > sem_pos, \
        f"FILE_SLOT_ACQUIRE (pos={acqu_pos}) must be AFTER async with file_sem (pos={sem_pos})"
    assert start_pos > sem_pos, \
        f"DOWNLOAD_START (pos={start_pos}) must be AFTER async with file_sem (pos={sem_pos})"
    assert attempt_pos > sem_pos, \
        f"DOWNLOAD_ATTEMPT (pos={attempt_pos}) must be AFTER async with file_sem (pos={sem_pos})"
    print(f"  ✓ FILE_SLOT_ACQUIRE pos {acqu_pos} > async with pos {sem_pos}")
    print(f"  ✓ DOWNLOAD_START pos {start_pos} > async with pos {sem_pos}")
    print(f"  ✓ DOWNLOAD_ATTEMPT pos {attempt_pos} > async with pos {sem_pos}")

    # ── 6. No DOWNLOAD_START before semaphore ──
    before_sem = src[:sem_pos]
    assert "DOWNLOAD_START" not in before_sem, \
        "DOWNLOAD_START should NOT appear before async with file_sem"
    assert "DOWNLOAD_ATTEMPT" not in before_sem, \
        "DOWNLOAD_ATTEMPT should NOT appear before async with file_sem"
    print(f"  ✓ semaphore 之前无 DOWNLOAD_START/ATTEMPT")

    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
