"""Disk-consistent download progress (P0-D).

Issue #20: total progress used ``SUM(downloaded_bytes)`` straight from the DB,
so a ``registered`` row (or a stale row for a deleted/truncated file) counted
bytes that were not really on disk, producing values over 100%.

These helpers turn observed on-disk file states into a verified summary that can
never exceed 100%:

- a file counts as complete only when the final file exists and its size matches
  the expected size;
- ``.part`` counts only its actual size (never the expected size);
- a final file larger than expected is flagged as overage and is not trusted for
  the verified byte count;
- the progress ratio is clamped to ``[0, 1]``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ObservedFile:
    """Observed on-disk state for one expected file."""

    expected_bytes: int
    final_bytes: int | None = None   # size of the final file, or None if absent
    part_bytes: int | None = None    # size of the .part file, or None if absent


@dataclass(frozen=True)
class VerifiedDownloadSummary:
    verified_bytes: int
    complete_files: int
    overage_files: int
    total_files: int

    @property
    def progress(self) -> float:
        """Truthful ratio, never pushed to 100% by unknown-size files.

        Only files with a known expected size contribute to the byte ratio:
        unknown-size (``expected == 0``) content never enters the numerator,
        so it cannot inflate the completion of files whose size is known.
        When there are no known-size files at all, fall back to the fraction of
        observed complete files.
        """
        known_verified = 0
        known_expected = 0
        for file in self._files:
            expected = max(0, int(file.expected_bytes or 0))
            if expected <= 0:
                continue
            known_expected += expected
            if file.final_bytes is not None:
                final = max(0, int(file.final_bytes))
                if final == expected:
                    known_verified += final
                elif final > expected:
                    # Oversized final file is anomalous: not trusted.
                    pass
                else:
                    known_verified += final
            elif file.part_bytes is not None:
                known_verified += min(max(0, int(file.part_bytes)), expected)
        if known_expected > 0:
            return max(0.0, min(1.0, known_verified / known_expected))
        if self.total_files > 0 and self.complete_files >= self.total_files:
            return 1.0
        return 0.0

    @property
    def has_overage(self) -> bool:
        return self.overage_files > 0

    _files: tuple[ObservedFile, ...] = ()


def verified_download_progress(files: list[ObservedFile]) -> VerifiedDownloadSummary:
    """Compute a disk-verified progress summary for a list of expected files."""
    verified = 0
    complete = 0
    overage = 0
    for file in files:
        expected = max(0, int(file.expected_bytes or 0))
        if file.final_bytes is not None:
            final = max(0, int(file.final_bytes))
            if expected > 0:
                if final == expected:
                    verified += final
                    complete += 1
                elif final > expected:
                    # Oversized final file is anomalous: do not trust the bytes.
                    overage += 1
                else:
                    verified += final
            else:
                # Unknown expected size: an existing final file is best-effort
                # treated as verified content.
                verified += final
                complete += 1
        elif file.part_bytes is not None:
            part = max(0, int(file.part_bytes))
            verified += min(part, expected) if expected > 0 else part
    return VerifiedDownloadSummary(
        verified_bytes=verified,
        complete_files=complete,
        overage_files=overage,
        total_files=len(files),
        _files=tuple(files),
    )
