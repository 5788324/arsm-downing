# ARSM Suite PR-1 Direct-Source Release-Blocker Fix

- Reviewed baseline: `main@50346f9da9a5d24dda99f7d8c6c21e2f9210c1a6`
- Delivery: direct modification of the V6-applied complete source snapshot; no patch applicator and no Git write
- Version remains `0.9.0-rc.3`; this is not a 1.0 release

## User-facing fixes

1. Failed retry reconciles final and `.part` bytes, complete partials, zero-byte retries, missing terminal files, metadata refresh and oversized-file review.
2. Single retry, batch resume and tray resume use one core recovery path with duplicate-click guards and structured results.
3. Pause, pause-and-hide and persistent cancel have separate semantics and separate runtime markers.
4. Cancel during metadata, cover or worker cancellation cannot resurrect the task or regress the UI to Paused.
5. Completed/registered SQLite labels are verified against disk before they are trusted.
6. Existing unresolved rows prevent a work from being marked completed after only a subset succeeds.
7. Re-adding cancelled work offers an explicit resume action; cancelled rows are visible even for orphan download records.
8. Library anomaly mode is generation-safe and no longer references undefined variables. The delivery applicator locates `LibraryView._apply_anomalies` by AST and leaves `_apply_cards()` category/sort text unchanged.
9. Flet receives local cover paths only. Cover fetches use NetworkKernel, format-aware atomic cache publishing and default-off direct fallback.
10. Settings validate before persistence, clean failed probes, restore durable/runtime state and refresh future-task path snapshots.
11. High-risk tools require a two-step, session-only advanced mode. Cancelled rows are terminal for maintenance: they do not block VACUUM or queue-cleanup preview, but they continue to protect metadata required by explicit retry.
12. External Intake Execute remains frozen.

## Added regression suites

- `tests/test_release_blocker_fixes.py`
- `tests/test_release_blocker_user_journeys.py`
- `tests/test_release_blocker_ui_contracts.py`

## Safety boundaries

- No automatic migration of `E:\arsm`.
- No formal `history.db`, `queue.json` or existing `.part` access.
- No installer/data-home refactor.
- No Git branch, commit, push, tag, release or PR creation by ChatGPT.

## Validation status

- Direct-source portable focused pytest: `49 passed`.
- Non-Flet product tests: `234 passed`; non-UI import smoke: `19 passed`; maintenance-focused tests: `10 passed`.
- Windows full pytest, release check with tests, PyInstaller build and real GUI/tray gates remain pending Codex evidence.
- No Windows pass is inferred from portable tests.
