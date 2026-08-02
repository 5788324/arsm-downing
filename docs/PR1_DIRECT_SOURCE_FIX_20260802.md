# PR1 Direct-Source Fix — 2026-08-02

## Decision

The V1–V6 patch-applicator workflow is retired. This candidate is maintained as a complete source tree derived from the successfully applied V6 Windows worktree at `main@50346f9da9a5d24dda99f7d8c6c21e2f9210c1a6`.

## Resolved blocker

`cancelled` is a durable terminal state. It has two distinct maintenance properties:

- it does **not** represent active I/O and therefore does not block VACUUM or queue-cleanup preview;
- it remains eligible for explicit retry and therefore protects its metadata cache from TTL cleanup.

Implementation constants:

- `MAINTENANCE_BLOCKING_STATUSES`
- `METADATA_PROTECTED_STATUSES`
- `TERMINAL_QUEUE_STATUSES`

The compatibility name `ACTIVE_STATUSES` now aliases only the maintenance-blocking set.

## Portable evidence

- PR1 focused suites: 49 passed
- Non-Flet product suite: 234 passed
- Non-UI import smoke: 19 passed
- Maintenance semantic subset: 10 passed
- compileall: PASS
- release_check --skip-tests: PASS

The current container cannot install the pinned Flet 0.27.6 package. Full Windows pytest, PyInstaller and GUI/tray evidence remain mandatory.

## Data boundary

No formal database, config, queue, existing partial download, or `E:\arsm` path was accessed. No Git write was performed.

## Windows 实机证据（2026-08-02）

- Python 3.12 isolated venv：focused 49 passed；full 294 passed, 3 skipped。
- elease_check --skip-tests：ready=true；PyInstaller one-folder：PASS；EXE：8,320,551 bytes，SHA-256 6c84d11e7b028cbb96ffa5b58cba56c91ae09ceb7fcc2af8abaebd3c928ad580。
- Flet GUI：下载中心、资源库、系统工具、设置可往返；批量粘贴可取消且队列仍为零；External Intake 保持冻结；三轮启动/关闭和托盘彻底退出后无残留。
- 未接触正式数据。高 DPI（125%/150%/200%）视觉复核仍待用户实际显示缩放。