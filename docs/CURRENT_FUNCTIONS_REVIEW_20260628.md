# ARSM Downing Current Functions Review - 2026-06-28

This document is a handoff for external AI/code review. It describes the current shipped behavior after the RC8/RC9 cleanup and UI reset work.

## Current Runtime State

- Main output library: `E:\arsm`
- Current DB: `history.db`
- Current queue file: `queue.json`
- Current clean library counts after zero-error cleanup:
- `works = 184`
- `library_items = 184`
- `library_index = 184`
- `downloads = 0`
- `library_scan_runs = 1`
- `library_items warnings = 0`
- non-verified works = 0
- `PRAGMA integrity_check = ok`
- All visible log files under `logs/` were cleared to 0 bytes.

## Cleanup Boundary

- Bad or incomplete works were not permanently erased immediately.
- They were moved out of the active library into same-drive quarantine:
- `E:\arsm_removed_zero_error_20260628_134617` and `E:\arsm_removed_partial_20260628_135637`
- Audit report:
- `.local_backups/zero_error_same_drive_20260628_134617/zero_error_same_drive_report.json` and `.local_backups/partial_cleanup_20260628_135637/partial_cleanup_report.json`
- Project-root DB backups were moved to:
- `.local_backups/root_db_backups_20260628_135415`
- `.local_backups/` is ignored by Git and must not be committed.

## Core Data Model

### `works`

Purpose: canonical known works shown by dashboard/search and used by migration/download logic.

Important columns:
- `rj_id`: canonical RJ id.
- `title`: metadata title when available.
- `size_bytes`: current total disk size for the work.
- `local_path`: active folder path.
- `cover_url`: metadata cover fallback.
- `status`: current work state.

Current desired clean state:
- Active local library works should be `verified`.
- Incomplete or abnormal works should not stay visible in the clean resource library.

### `downloads`

Purpose: active or historical per-file download task rows.

Current reset state:
- Table is intentionally empty.
- New downloads should repopulate it from fresh metadata and track lists.
- Historical `failed`, `registered`, `stale`, `ignored`, and `paused` rows were cleared to avoid old queue pollution.

### `metadata_cache`

Purpose: cached metadata and track list from API.

Current behavior:
- Used for cover fallback, title lookup, and retry/rebuild flows.
- Cache may contain entries for works no longer active in `E:\arsm`; this is acceptable unless a future cleanup explicitly targets cache.

### `library_items`

Purpose: current indexed resource-library view.

Important columns:
- `rj_id`
- `folder_path`
- `folder_name`
- `total_files`
- `total_size`
- file-type counts
- `has_audio`
- `has_cover`
- `warnings_json`
- `scan_run_id`

Current desired clean state:
- `library_items` count should match `works` count after cleanup.
- `warnings_json` should be `[]` for all active entries.

### `library_index`

Purpose: legacy/library scan lookup table used by duplicate checks and scan flows.

Current desired clean state:
- Count should match active indexed works.
- It should only point to active valid folders under configured library roots.

## Download Page

File: `ui/views/download_view.py`

Functions:
- Add RJ to download queue.
- Batch import RJ ids from a file.
- Start, pause, retry, and clear visible queue cards.
- Show per-work and per-file progress.
- Use cached metadata cover or local cover fallback.
- Hide terminal works from active queue when only historical failed/paused residue exists.
- Make RJ id selectable/copyable in cards.

Important current behavior:
- `queue.json` is not the source of truth for old progress.
- `downloads` table drives active queue reconstruction.
- Completed/verified works should not reappear on the download page just because old failed rows once existed.

Review focus:
- Check whether active workers still correctly repopulate `downloads` after the full reset.
- Check that failed new downloads are visible enough for real troubleshooting, while old deleted rows remain gone.
- Check whether UI update throttling avoids freezes during multi-file downloads.

## Resource Library Page

File: `ui/views/library_view.py`

Functions:
- Shows all indexed active works from `library_items`.
- Shows searchable card grid.
- Has resource/anomaly modes.
- Displays local cover first and metadata cover fallback when available.
- RJ ids are selectable/copyable.
- Anomaly categories include alias, missing path, not indexed, old root, empty directory, no images, path mismatch.

Current desired behavior:
- After the zero-error cleanup, anomaly count should be 0.
- `works` and `library_items` should both be 184.
- Any future externally downloaded folder copied into `E:\arsm` should be rescanned, normalized by RJ id, and either indexed cleanly or quarantined.

Review focus:
- Verify card heights and cover alignment.
- Verify no mojibake/`???` text remains.
- Verify anomaly filters show meaningful Chinese labels when anomalies exist again.

## Dashboard Page

File: `ui/views/dashboard_view.py`

Functions:
- Shows live DB stats from `works` and `library_items`.
- Shows works count, works size, library index count, indexed file count, indexed size.
- Shows a small source note with `works`, `library_items`, and diff.
- Shows simple achievement cards.

Important current change:
- Removed hard-coded scan count.
- All displayed counts are DB-backed.

Review focus:
- Check whether card sizes align visually with the rest of the UI.
- Check whether source wording is clear enough for non-technical users.

## Tools Page

File: `ui/views/tools_view.py`

Functions:
- Run basic diagnostics.
- Test network/proxy settings.
- Scan library paths and rebuild legacy library index.
- Diagnose failed downloads.
- Migration dry-run and verification.
- Clear invalid queue.
- VACUUM database.
- Clear metadata cache placeholder.
- Preview/re-enable stale/ignored backlog rows.

Important current behavior:
- Migration target must come from `config.output_dir`.
- `library_paths` are source scan roots, not migration target selectors.
- Historical backlog should be empty after reset unless new failed/stale rows are created later.

Review focus:
- Some lower-level logs still use English technical terms by design.
- Verify visible Chinese labels are not mojibake.
- Consider simplifying the tools page further for a beginner user.

## Settings Page

File: `ui/views/settings_view.py`

Functions:
- Configure output download directory.
- Configure additional library scan roots.
- Configure metadata, cover, and download proxies separately.
- Configure fallback-to-proxy behavior.
- Configure max concurrent downloads and sorting/tagging options.

Review focus:
- Validate scroll works.
- Validate path editing is safe and saves correct JSON.
- Consider adding a folder picker later.

## Migration

Files:
- `core/migration.py`
- `ui/views/tools_view.py`

Current accepted rules:
- Target base is `config.output_dir`.
- Never infer target from `library_paths`.
- Already-on-target works are skipped.
- Pending/active/queued works are rejected.
- `.part` files reject migration.
- `dry-run`, `execute`, and `verify` must use the same target resolution rule.

Current user preference:
- The user prefers automatic delete-source after verified move/copy in future, but only if rollback safety is strong.
- Current code still retains explicit migration safety checks.

## Library Cleanup Policy

Current policy after the latest user decision:
- Active library should be clean.
- If a work has missing files, `.part`, empty directory, no images, or unresolved warnings and cannot be fixed in one pass, remove it from active library and quarantine/delete it.
- Do not leave visible warning items in the resource library.
- Keep a backup/quarantine trail outside active `E:\arsm`.

Important caution:
- This policy is intentionally aggressive and user-approved for this stage.
- Future code should make this operation explicit and auditable, not automatic on every scan.

## Known Remaining Risks

- `metadata_cache` was not fully refreshed for all active works in the last cleanup. It may contain stale entries or entries for quarantined works.
- File-list comparison against live metadata was not completed for every work in the final zero-error cleanup. The final action prioritized removing visible anomalies and later removing 12 newly detected `partial` works from the active library.
- `logs/` files were cleared manually. New runtime activity will recreate log content.
- Quarantined folders on `E:\arsm_removed_zero_error_20260628_134617` and `E:\arsm_removed_partial_20260628_135637` are outside the active library and should not be auto-scanned unless intentionally restored.
- `tools_view.py` still contains complex migration/backlog functions; review should ensure no accidental DB writes happen from preview actions.
- New external resources copied into `E:\arsm` may have non-standard folder names. The next stage should add a formal "normalize external library" workflow.


## Latest Local Cleanup - 2026-06-28 13:56

After the initial zero-error cleanup, 12 works were later marked `partial` by metadata/file verification. They were moved out of the active library according to the user-approved rule: if an issue cannot be fixed immediately, keep it out of the active library.

- Quarantine: `E:\arsm_removed_partial_20260628_135637`
- Audit: `.local_backups/partial_cleanup_20260628_135637/partial_cleanup_report.json`
- Final active state: `works=184`, `library_items=184`, `downloads=0`, `warnings=0`, `non_verified=0`, DB integrity `ok`.

## Suggested Next Stage

Implement a controlled external-resource intake workflow:

1. Scan `E:\arsm` top-level folders.
2. Normalize RJ id and folder name from live metadata.
3. Fetch fresh metadata and track list.
4. Compare disk files with expected metadata tracks.
5. If complete: update `works`, `library_items`, `library_index`.
6. If incomplete but recoverable: create new queued downloads for missing files.
7. If invalid/unrecoverable: quarantine immediately and keep it out of active library.
8. Show a single review dialog: fixed, queued for redownload, quarantined.

## Review Questions For Other AI

- Is the current data reset safe enough after `downloads=0`?
- Can new downloads recreate all necessary `downloads` rows without depending on old history?
- Are `works` and `library_items` now consistently treated as active library state?
- Are quarantined items isolated enough from future scans?
- Are UI pages still using stale hard-coded counts anywhere?
- Is there any path where `library_paths` can still be misused as a migration target?
- Should `metadata_cache` be rebuilt or pruned in the next stage?
- Should "zero-error cleanup" become a formal tool with dry-run and confirmation?
