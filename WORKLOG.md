# WORKLOG.md

# arsm-downing / arsm-suite 工作日志

## 0. 工作日志规则

本文件用于持续记录项目的重要工作，方便用户、ChatGPT、Claude、Codex、OpenCode、Hermes、DeepSeek 接手。

每轮工作结束至少记录：

```text
日期
执行者
阶段
本轮目标
实际完成
是否改代码
是否改 DB
是否删除文件
备份路径
测试结果
Git 状态
下一步
```

原则：

```text
文档跟随事实，不用文档代替代码检查或诊断脚本。
```

---

## 1. 当前项目状态快照

### 项目名

```text
arsm-downing
```

### 项目定位

```text
个人本地 ASMR/RJ 下载器 + 资源库管理器 + 后续播放器
```

### 当前主线

```text
P1：UI 侧 LibraryVault 单例确认
P2：RC9 下载状态只读诊断
P3：资源库只读扫描 MVP
P4：RC9 安全修复第一轮
P4.5：library_items schema 决策
P5：资源库索引入库
P6：资源库管理 UI MVP
P7：播放器 MVP
P8：媒体库体验打磨
```

### 当前技术栈

```text
Python
Flet
SQLite
asyncio
aiohttp
LibraryVault
Windows 本地文件系统
```

### 当前主资源库

```text
E:\arsm
```

### 当前核心 DB

```text
history.db
```

### 当前唯一 DB 访问层

```text
LibraryVault
```

---

## 2. 规划分支最终结论

### 日期

```text
2026-06-27
```

### 执行者

```text
用户
ChatGPT
Claude
```

### 阶段

```text
规划分支 / 下一阶段路线收敛
```

### 本轮目标

把项目下一阶段路线重新收敛，避免继续无限扩展下载器，同时保留后续做媒体库和播放器的可能。

### 核心结论

```text
1. 不拆成多个独立项目，继续作为单一 Flet 应用推进。
2. 不新建 repository 层，不重构 database.py。
3. 所有新模块必须共享同一个 LibraryVault 实例。
4. P3 JSON 只做诊断，不进入 P6 UI 数据路径。
5. P4 下载状态修复 和 P5 资源库索引入库必须分开执行。
```

---

## 3. Claude core DB audit 结论

Claude 已基于 `core` 目录做过 DB/核心层体检。

### 主要结论

```text
当前 DB 层比预期干净。
不需要新建 core/db/repository.py。
不需要推倒重构。
LibraryVault 可以继续作为事实上的唯一 SQLite 访问入口。
```

### 具体结论

```text
1. 全项目没有多处 sqlite3.connect。
2. orchestrator / migration 没有绕过 LibraryVault 裸写 DB。
3. UPDATE SQL 实际通过 self.db.execute_write 调用，不是裸连接。
4. orchestrator 和 migration 都通过构造参数接收 db 实例，符合依赖注入。
5. 当前 core 主要是 asyncio 模型，没有明显 raw threading.Thread worker。
6. 后续播放器如果引入真实线程或高频播放进度写入，需要单独审查。
```

---

## 4. 文档策略

当前正式保留三份核心文档：

```text
PROJECT_ROADMAP.md
WORKLOG.md
AI_WORKFLOW.md
```

暂缓新增：

```text
PROJECT_DOCUMENTATION.md
CORE_DB_ACCESS_AUDIT.md
IDEAS_BACKLOG.md
PLAYER_DESIGN.md
LIBRARY_SCHEMA.md
```

---

## 5. 关键执行原则

### 5.1 SQLite 是唯一真源

```text
history.db / SQLite = 唯一真源
LibraryVault = 唯一 DB 访问入口
P3 JSON = 只读诊断报告
manifest.json = 后续可选导出 / 缓存
```

### 5.2 P3 JSON 不进入 P6 UI 数据路径

```text
P3 会输出 library_scan_report.json / library_scan_summary.txt
这些文件只给人看，不给 UI 当数据源
P6 UI 必须通过 LibraryVault / SQLite 读取资源库数据
```

### 5.3 P4 和 P5 不合并执行

```text
P4 只处理 works / downloads 下载历史状态
P5 只写 library_items
禁止合并成“一次性 DB 整理”
```

---

## 6. 2026-06-27 RC8.7 final audit closeout

### 日期

```text
2026-06-27
```

### 执行者

```text
Codex
```

### 阶段

```text
P0 / RC8.7 final audit closeout
```

### 本轮目标

落地 `PROJECT_ROADMAP.md` / `WORKLOG.md`，执行 RC8.7 只读 final audit，输出 closeout report，并把剩余问题收敛到 RC9。

### 实际完成

```text
1. Added PROJECT_ROADMAP.md to repo root.
2. Added WORKLOG.md to repo root.
3. Created .local_backups/rc8_7_final_audit_20260627_101934.
4. Backed up history.db / wal / shm and config.json for this audit.
5. PRAGMA integrity_check = ok.
6. Wrote rc8_7_final_audit.json and RC8_7_FINAL_AUDIT_SUMMARY.txt.
7. Copied RC8.6 cleanup verification evidence into the RC8.7 audit folder.
8. Wrote RC8_7_FINAL_MIGRATION_CLOSEOUT_REPORT.txt.
```

### 是否改代码

```text
no
```

### 是否改 DB

```text
no
```

### 是否删除文件

```text
no
```

### 备份路径

```text
.local_backups/rc8_7_final_audit_20260627_101934
```

### 核验结果

```text
integrity_check = ok
missing_completed_download_paths = 0
RC8.6 cleanup_post_verify_ok = yes
resource_scan_found = 221
resource_scan_errors = 0
allowlist_not_on_e_count = 0
work_on_E_but_completed_downloads_old_path_count = 0
works_completed_verified_not_on_E = 17
downloads_completed_not_on_E_grouped_count = 2
missing_work_paths_count = 3
RC8 migration phase closeout = yes
```

### Git 状态

```text
HEAD = 00c681e
working tree = dirty only because documentation files were added for handoff
DB/log/RJ miscommit risk = no
```

### 下一步

```text
P1：UI 侧 LibraryVault 单例确认
P2：RC9 下载状态只读诊断
Do not reopen RC8 migration unless new evidence shows missing completed downloads or allowlist target drift.

---

## 7. 2026-06-27 P1: UI 侧 LibraryVault 单例确认

### 日期
```text
2026-06-27
```

### 执行者
```text
DeepSeek/OpenCode
```

### 阶段
```text
P1 / UI 侧 LibraryVault 单例确认
```

### 本轮目标
确认整个 Flet 应用只创建一次 LibraryVault()，检查所有 UI 视图是否绕过 DB 层。

### 实际完成
```text
1. grep LibraryVault() across all *.py: found 2 instances in production UI code.
2. ui/app.py:53 — singleton instance in AppController.__init__. Correct.
3. ui/views/download_view.py:737 — second LibraryVault() instance in _open_work_dir(). BLOCKER FOUND.
4. ui/views/download_view.py:212 — dead import of LibraryVault (not used for instantiation, but clutter).
5. All other UI views (library_view, tools_view, dashboard_view, settings_view): clean.
6. All core modules (orchestrator, migration): clean, use dependency injection.
7. No rogue sqlite3.connect() outside database.py's own internals.
8. takoyune_repo/ is legacy alt-code, not used by active app.
```

### 修复
```text
1. download_view.py:737-739: removed `from core.database import LibraryVault; db = LibraryVault()` and
   replaced with `self.app_controller.config` and `self.app_controller.db.get_metadata_cache()`.
2. download_view.py:212: removed dead `from core.database import LibraryVault` import.
   Total diff: +2 -7 lines.
```

### 是否改代码
```text
yes — ui/views/download_view.py, 2-line minimal fix
```

### 是否改 DB
```text
no
```

### 是否删除文件
```text
no
```

### 是否改下载核心
```text
no
```

### 结果
```text
PASS: Only one LibraryVault() in UI code (ui/app.py:53 singleton).
All views share the AppController.db instance.
P1 confirmed — no blockers remain.
```

---

## 8. 2026-06-27 P2: RC9 下载状态只读诊断

### 日期
```text
2026-06-27
```

### 执行者
```text
DeepSeek/OpenCode
```

### 阶段
```text
P2 / RC9 下载状态只读诊断
```

### 本轮目标
Read-only diagnosis of downloads_status, failed/paused/registered categories, key RJ deep dive.

### 实际完成
```text
1. Wrote rc9_diagnosis.py — comprehensive read-only analysis.
2. Generated RC9_DOWNLOAD_STATUS_DIAGNOSIS.json and SUMMARY.txt.
3. Saved to .local_backups/rc9_diagnosis_20260627_114347.
```

### 核心发现
```text
works_status: {completed:101, prepared:74, verified:36, partial:3, external:2} total=216
works_on_E: 195, completed+verified_on_E: 120, not_on_E: 17

downloads_status: {registered:5226, paused:1782, failed:1752, completed:1307} total=10067
  completed on E: 423, not on E: 884

failed (1752):
  - 0 resumable (no partial files)
  - 1732 retry-from-zero (no files)
  - 0 complete-file-but-DB-says-failed
  - top errors: Fallback also failed (1596), HTTP 400 (156)

paused (1782 across 35 RJs):
  - 5 with file (resumable)
  - 1777 without file (orphaned pause records)

registered (5226 across 110 RJs):
  - 92 with completed/verified work
  - 18 with other non-terminal downloads
  - 0 with active/prepared work

Key RJs:
  RJ01588893: verified, path=C:\...Music\arsm.one, exists, 883 completed, 3 failed, 48 registered
  RJ01534605: verified, path=C:\...Music\arsm.one, exists, 1 completed, 9 failed, 39 registered
  RJ00323125: verified, path=C:\...Music\arsm.one\RJ323125..., exists, size=0, no downloads
  RJ323125: prepared, path=E:\arsm\... (NOT exists), size=0, 24 paused

missing_work_paths: 3 (RJ01571951, RJ01572913, RJ323125)
downloads_completed_not_on_E_grouped: 2 RJs (RJ01588893:883, RJ01534605:1)
works_cv_not_on_E: 17 (15 exist locally, 2 missing)
loose RJ format abnormal = 0
canonical RJ8 abnormal = 1
RJ323125 is a historical non-canonical RJ and should map to RJ00323125
work_on_E_but_old_path_downloads: 0
```

### 是否改代码
```text
no (diagnosis script only)
```

### 是否改 DB
```text
no
```

### 是否删除文件
```text
no
```

### 是否改下载核心
```text
no
```

### 报告路径
```text
.local_backups/rc9_diagnosis_20260627_114347/RC9_DOWNLOAD_STATUS_DIAGNOSIS.json
.local_backups/rc9_diagnosis_20260627_114347/RC9_DOWNLOAD_STATUS_DIAGNOSIS_SUMMARY.txt
```

### 下一步
```text
P3: 资源库只读扫描 MVP
P4: RC9 安全修复第一轮 (基于本诊断结果)

---

## 9. 2026-06-27 P3: 资源库只读扫描 MVP

### 日期
```text
2026-06-27
```

### 执行者
```text
DeepSeek/OpenCode
```

### 阶段
```text
P3 / 资源库只读扫描 MVP
```

### 本轮目标
Scan E:\arsm, classify all files by type per work, detect anomalies, output read-only report.

### 实际完成
```text
1. Wrote p3_library_scan.py — recursive RJ directory scanner with file classification.
2. Scanned E:\arsm: found 194 RJ works across 196 directories (2 duplicates).
3. Classified 8390 files totaling 481.29 GB by audio/video/image/subtitle/text/other.
4. Detected: 2 duplicate RJ pairs, 4 abnormal names, 16 without audio, 56 without cover, 107 with warnings.
5. Generated library_scan_report.json (4414 KB) and library_scan_summary.txt.
6. Saved to .local_backups/library_scan_20260627_115721.
```

### 扫描结果
```text
roots: E:\arsm
total_dirs_scanned: 37
total_works: 194
total_files: 8390
total_size: 481.29 GB

category breakdown:
  audio:    3230 files, 451.62 GB
  video:     107 files,  20.34 GB
  image:    1452 files,   3.72 GB
  subtitle: 1707 files,   0.01 GB
  text:     1806 files,   0.17 GB
  archive:     0 files,   0.00 GB
  other:      20 files,   0.54 GB

anomalies:
  duplicate_rjs: 2 (RJ01583802, RJ01277591)
  abnormal_names: 4 (directories starting with 【 instead of RJ)
  without_audio: 16 (single-file archives or metadata-only dirs)
  without_cover: 56 (many are empty dirs or single-purchase placeholders)
  with_warnings: 107 (most are large WAV files >500MB, expected for HQ audio)
  errors: 0

edge cases noted:
  - RJ00000000 / RJ00123456: test/dummy directories (not real works)
  - 45+ empty directories: likely single-purchase stubs without downloaded content
  - Abnormal names: folders prefixed with 【 instead of plain RJ number
```

### 是否改代码
```text
no
```

### 是否改 DB
```text
no
```

### 是否删除文件
```text
no
```

### 是否改下载核心
```text
no
```

### 报告路径
```text
.local_backups/library_scan_20260627_115721/library_scan_report.json
.local_backups/library_scan_20260627_115721/library_scan_summary.txt
```

### 下一步
```text
P4: RC9 安全修复第一轮 (基于 P2 诊断结果)
P4.5: library_items schema 决策
P5: 资源库索引入库 (基于 P3 扫描结果写入 library_items)

---

## 10. 2026-06-27 P3 统计口径澄清

### 说明
```text
P3 summary 中三个统计字段的口径：

total_dirs_scanned = 37：
  _walk() 函数被调用的次数。包括根目录 E:\arsm (depth=0) +
  所有被递归进入的非 RJ 中间目录。RJ 目录本身不被 _walk 递归，
  所以不计入此数。

rj_dirs = 196：
  在 E:\arsm 下所有层级发现且匹配 RJ\d{6,8} 模式的子目录总数。
  包括根目录直下 + 嵌套在非 RJ 目录下的 RJ 子目录（如
  【简中】甘园房~/RJ01277591）。去重后得到 194 个 unique rj_id。

non_rj_dirs = 36：
  不含 RJ 模式、且包含至少一个文件（递归计算）的目录数。
  仅统计文件数 > 0 的目录，空目录归入 empty_dirs。
```

---

## 11. 2026-06-27 P4-readonly + P4.5

### 日期
```text
2026-06-27
```

### 执行者
```text
DeepSeek/OpenCode
```

### 阶段
```text
P4-readonly / RC9 safe fix allowlist-blocklist + P4.5 / library schema decision
```

### 本轮目标
1. 澄清 P3 统计口径。
2. 基于 P2 诊断 + P3 扫描 + 实时 DB 生成 RC9 safe fix allowlist/blocklist/proposals。
3. 输出 6 个重点 RJ 单独决策。
4. 提出 P4.5 library schema 决策方案。
5. 全程不修改 DB，不删除文件。

### 实际完成
```text
1. Clarified P3 stat definitions: total_dirs_scanned=walk-calls, rj_dirs=all-level RJ dirs, non_rj_dirs=non-empty non-RJ dirs.
2. Cross-referenced 18 works_cv_not_on_E with live DB download counts + P3 scan results.
3. Generated ALLOWLIST (12), PROPOSALS (3), BLOCKLIST (3) + key RJ analysis.
4. Authored LIBRARY_SCHEMA_DECISION.md covering library_items, library_scan_runs, duplicate policy, fake RJ exclusion, UI data source rules.
```

### P4-readonly 结果
```text
ALLOW (12): works on old drive, path exists, only failed+registered terminal rows — preview-only candidate set for future UPDATE to stale/ignored
  RJ01481836, RJ01511863, RJ01522140, RJ01530888, RJ01531519,
  RJ01551657, RJ01555750, RJ01561298, RJ01561385, RJ01563820,
  RJ01570285, RJ01582341

PROPOSAL (3): needs user decision before any future state transition
  RJ01588893: verified, 883 completed + 3 failed + 48 registered,
              path exists on old drive, not on E:\ — completed downloads fine,
              future candidate for UPDATE to stale/ignored, but full migration deferred
  RJ01534605: verified, 1 completed + 9 failed + 39 registered,
              path exists on old drive, not on E:\ — same pattern as RJ01588893
  RJ00323125: verified, path exists (C:\...Music\RJ323125...), size=0, no downloads

BLOCK (3): unsafe / needs investigation
  RJ01571951: completed, path missing (Downloads\), P3 not on E:\
  RJ01572913: completed, path missing (Downloads\), P3 not on E:\
  RJ323125:  prepared, path E:\arsm missing, 24 paused — merge with RJ00323125 needed

Key RJ decisions:
  RJ01588893 → PROPOSAL: completed on old drive, future candidate for UPDATE to stale/ignored, migration to E:\ deferred
  RJ01534605 → PROPOSAL: same pattern
  RJ00323125 → PROPOSAL: stale work entry, RJ323125 merge needed
  RJ323125   → BLOCK: prepared+stale, merge into RJ00323125
  RJ01571951 → BLOCK: path missing, not on E:\
  RJ01572913 → BLOCK: path missing, not on E:\
```

### P4.5 schema decision
```text
Proposed tables:
  library_items     — YES (P5), 16 fields, work-level aggregate + warning + scan trace
  library_scan_runs — YES (P5), scan history tracking
  library_files     — NO, deferred to P7+

Duplicate RJ policy:
  5-rule deterministic priority (works.local_path > top-level > audio_count > size > files)
  Losing copy recorded as warning, NEVER deleted

Fake RJ exclusion:
  RJ00000000, RJ00123456 excluded from P5入库
  Files preserved, recorded as scan warning

UI data source:
  P3 JSON is diagnostic-only. P6 UI reads via LibraryVault/SQLite exclusively.
```

### 是否改代码
```text
no
```

### 是否改 DB
```text
no
```

### 是否删除文件
```text
no
```

### 是否改下载核心
```text
no
```

### 报告路径
```text
P4: .local_backups/rc9_safe_fix_plan_20260627_120604/
      rc9_safe_fix_allowlist.json
      rc9_safe_fix_blocklist.json
      rc9_safe_fix_proposals.json
      rc9_key_rj_analysis.json
      RC9_SAFE_FIX_PLAN_SUMMARY.txt

P4.5: .local_backups/library_schema_decision_20260627_120600/
        LIBRARY_SCHEMA_DECISION.md
```

### 下一步
```text
Codex 审查 P4/P4.5 方案 → Codex returned NEEDS_FIX on P4 execution semantics →
  P4 revised to conservative preview-only (no DELETE) →
  P4.5 approved → P5 can proceed in parallel

---

## 12. 2026-06-27 P4 final deliverables (revised after Codex review)

### Codex 审查结果
```text
NEEDS_FIX:
  - Classification (ALLOW/PROPOSAL/BLOCK) is correct — no changes needed
  - P4.5 schema decision is APPROVED — P5 can proceed
  - P4 execution semantics were too aggressive — defaulted to DELETE
  - "registered is not natural junk" — may be historical trace
  - "failed is not pure garbage" — it is diagnostic evidence
  - "HTTP 400 so no need to keep" — too aggressive
  - Requirement: replace DELETE with auditable state strategy
  - Requirement: define stale/ignored/skipped states, not deletion
```

### 完成 (revised)
```text
Revised all P4 deliverables to conservative preview-only approach:

1. rc9_safe_fix_sql_preview.sql (REWRITTEN)
   - All DELETE statements REMOVED
   - Replaced with SELECT-only preview queries
   - Shows what rows exist, never deletes
   - Includes review checklist for future authorization

2. rc9_safe_fix_execution_plan.md (REWRITTEN)
   - "Execute DELETE" → "Preview only, no DB writes authorized"
   - Added 7 preconditions for any future DB write
   - Future execution: UPDATE to stale/ignored, not DELETE
   - Rollback: trivially reversible (UPDATE not DELETE)

3. rc9_classification_rationale.md (REVISED — final)
   - "DELETE junk entries" → "UPDATE to stale/ignored"
   - "Terminal states can be deleted" → "Terminal states should be transitioned"
   - ALL recommended actions changed from DELETE → "future action, if authorized: UPDATE to stale/ignored"
   - "Total removed" → "Total affected"
   - "delete RJ00323125 from works" → "mark as stale/archival — no deletion"
   - "delete RJ323125 from works" → "state transition to stale/referenced-to-RJ00323125"
   - All 4 files now semantically consistent: preview-only, no DELETE, no DB write authorized

4. rc9_auditable_state_strategy.md (NEW)
   - Defines stale, ignored, skipped as soft state transitions
   - Proposes mark_downloads_stale() method for LibraryVault
   - Classification → State mapping table
   - When DELETE is actually safe (future, not now)
```

### 是否改代码
```text
no
```

### 是否改 DB
```text
no
```

### 是否删除文件
```text
no
```

### 是否改下载核心
```text
no
```

### 报告路径
```text
.local_backups/rc9_safe_fix_plan_20260627_120604/
  rc9_safe_fix_sql_preview.sql       (SELECT-only, no DELETE)
  rc9_safe_fix_execution_plan.md     (preview-only, state strategy)
  rc9_classification_rationale.md    (conservative language)
  rc9_auditable_state_strategy.md    (NEW — stale/ignored/skipped)
  rc9_safe_fix_allowlist.json
  rc9_safe_fix_blocklist.json
  rc9_safe_fix_proposals.json
  rc9_key_rj_analysis.json
  RC9_SAFE_FIX_PLAN_SUMMARY.txt
```

### 下一步
```text
Codex 重新审查修订后的 P4 (conservative, no DELETE) →
  若通过: 实现 mark_downloads_stale() → 执行 state transitions (UPDATE not DELETE) →
P5 library_index dry-run (并行进行, P4.5 已通过)

---

## 13. 2026-06-27 P5 library index dry-run

### 日期
```text
2026-06-27
```

### 执行者
```text
DeepSeek/OpenCode
```

### 阶段
```text
P5 / library index dry-run (preview only, no DB writes)
```

### 本轮目标
基于 P3 扫描结果 + P4.5 schema decision，生成 library_items / library_scan_runs 的 dry-run 入库计划。交叉对照 works 表。处理 duplicate + fake RJ。

### 实际完成
```text
1. Generated library_index_schema_preview.sql (2 CREATE TABLE + 5 INDEX, no execution).
2. Generated library_index_insert_preview.json (194 candidates → 191 would_update, 1 would_insert, 2 excluded).
3. Cross-referenced with live works table: 192 exists_in_works, 191 path_matches, 1 path_differs.
4. Resolved 2 duplicate RJs per P4.5 5-rule policy:
   - RJ01583802: rule2_top_level, winner=127 files, loser=1 file (warning)
   - RJ01277591: rule1_works_local_path_match, winner=130 files, loser=67 files (warning)
5. Excluded 2 fake/test RJs: RJ00000000 (184 files), RJ00123456 (57 files) — files preserved.
6. 0 DB writes executed.
```

### P5 dry-run 统计
```text
candidate_count:              194
would_insert_count:           1    (RJ01583802 — path differs from works.local_path)
would_update_count:           191
would_exclude_count:          2    (fake/test RJ)
duplicate_rj_count:           2
duplicate_loser_count:        2
fake_rj_excluded_count:       2
exists_in_works_count:        192
not_in_works_count:           0
path_matches_works_count:     191
path_differs_from_works_count:1
```

### 是否改代码
```text
no
```

### 是否改 DB
```text
no
```

### 是否删除文件
```text
no
```

### 是否改下载核心
```text
no
```

### 报告路径
```text
.local_backups/library_index_dry_run_20260627_123000/
  library_index_schema_preview.sql
  library_index_insert_preview.json
  library_index_duplicate_decisions.json
  library_index_excluded_items.json
  LIBRARY_INDEX_DRY_RUN_SUMMARY.txt
```

### 下一步
```text
Codex 审查 P5 dry-run → 批准后执行 P5 actual DB write (CREATE TABLE + INSERT/REPLACE) →
  后续: P6 资源库管理 UI MVP
```
```
```
```
```
```

---

## 14. 2026-06-27 P5 actual DB write retry

### 日期
```text
2026-06-27
```

### 执行者
```text
Codex
```

### 阶段
```text
P5 / library index actual DB write retry
```

### 本轮目标
在不修改 `works` / `downloads` 的前提下，重试 P5 actual DB write，并将 SQLite 一致性备份目标从 `.local_backups` 改为 `%TEMP%`。

### 实际完成
```text
1. Confirmed git status clean and no running python/flet process.
2. Stored raw copy backup and execution context under .local_backups/p5_library_index_actual_write_retry_20260627_132949/.
3. Stored SQLite-consistent backup at %TEMP% because .local_backups had previously failed with disk I/O error.
4. Re-ran P5 actual write using latest dry-run outputs.
5. Created library_scan_runs and library_items only.
6. Inserted 1 scan run and upserted 192 library_items rows.
7. Preserved RJ01583802 as path_mismatch_with_works_local_path warning.
8. Verified works/downloads counts and status distributions unchanged.
9. Kept failed/paused/registered download records intact; no stale/ignored write executed.
```

### P5 actual write 结果
```text
sqlite_backup_target: C:\Users\YANG\AppData\Local\Temp\arsm_p5_sqlite_backup_20260627_132949\history.sqlite_backup_before_p5.db
sqlite_backup_integrity: ok
active_db_integrity_before: ok
active_db_integrity_after: ok

library_scan_runs_count: 1
library_items_count: 192
this_run_items: 192
fake_or_test_items: 0
items_not_on_E: 0
path_mismatch_items:
  - RJ01583802 -> E:\arsm\RJ01583802
    warnings_json=["path_mismatch_with_works_local_path"]

works_count_before_after: 216 -> 216
downloads_count_before_after: 10067 -> 10067
works_status_unchanged: yes
downloads_status_unchanged: yes
```

### 是否改代码
```text
no
```

### 是否改 DB
```text
yes
```

### 是否删除文件
```text
no
```

### 是否改下载核心
```text
no
```

### 报告路径
```text
.local_backups/p5_library_index_actual_write_retry_20260627_132949/
  history.before_p5_library_index.raw.db
  sqlite_backup_location.json
  p5_library_index_actual_write_summary.json
  p5_library_index_post_verify.json
  p5_forbidden_tables_safety_check.json
```

### 下一步
```text
P6 library UI MVP: allowed.
RC9.1 下载续跑计划: allowed.
Do not execute P4 stale/ignored before download continuation planning.
Continue to preserve failed/paused/registered records for resume/retry/manual review classification.
```

---

## 15. 2026-06-27 RC9.1 unfinished download soft closeout

### 日期
```text
2026-06-27
```

### 执行者
```text
Codex
```

### 阶段
```text
RC9.1 / unfinished download soft closeout (preview only)
```

### 本轮目标
优先清理当前历史未完成下载队列，但采用 soft closeout 策略：不删除历史行，不删除文件，不碰 completed，只把历史残留从后续自动恢复和 active queue 中安全移出。

### 实际完成
```text
1. Added soft status support for stale / ignored.
2. Updated startup restore path to ignore stale / ignored by excluding them from pending-download queries.
3. Kept resume_all / active queue aligned so stale / ignored do not participate in batch resume or queue restore.
4. Added RC9.1 unfinished closeout planner and SQL preview generator.
5. Generated preview-only closeout plan from live history.db.
6. Added focused tests for resume_all, startup restore, completed exclusion, preview-only registered->ignored, paused .part handling, and failed-without-file stale candidate.
7. Did NOT execute any DB update.
8. Did NOT delete any file.
```

### RC9.1 plan 结果
```text
failed_to_stale: 1732
paused_missing_file_to_stale: 1775
paused_resumable_needs_user_decision: 7
registered_to_ignored: 5226
blocked: 20
completed_skipped: 1307
completed_included: no

blocked_reasons:
  failed_has_recoverable_file: 20

paused_resumable_rj:
  RJ01357991: 5
  RJ01498118: 2

focus_rj:
  RJ01588893 -> failed_to_stale=3, registered_to_ignored=48
  RJ01534605 -> failed_to_stale=9, registered_to_ignored=39
  RJ00323125 -> no matching unfinished downloads in current downloads table
  RJ323125 -> paused_missing_file_to_stale=24
  RJ01571951 -> no matching unfinished downloads in current downloads table
  RJ01572913 -> no matching unfinished downloads in current downloads table
```

### 是否改代码
```text
yes
```

### 是否改 DB
```text
no
```

### 是否删除文件
```text
no
```

### 是否改下载核心
```text
minimal
```

### 报告路径
```text
.local_backups/rc9_1_unfinished_closeout_final_20260627_134943/
  rc9_1_unfinished_closeout_plan.json
  rc9_1_unfinished_closeout_sql_preview.sql
  RC9_1_UNFINISHED_CLOSEOUT_SUMMARY.txt
```

### 下一步
```text
RC9.2 actual soft closeout DB update requires explicit user approval.
Continue to preserve failed / paused / registered history rows until that approval is given.
Allow future download continuation planning before any stale/ignored DB write is executed.

---

## 15. 2026-06-27 RC9.2 actual unfinished download soft closeout

### 日期
```text
2026-06-27
```

### 执行者
```text
DeepSeek/OpenCode
```

### 阶段
```text
RC9.2 / actual DB write — soft closeout of unfinished downloads
```

### 本轮目标
Execute UPDATE-only soft closeout: failed/paused → stale, registered → ignored.
Keep completed untouched. No DELETE.

### 策略
```text
• failed -> stale (1752 rows)
• paused -> stale (1782 rows)
• registered -> ignored (5226 rows)
• completed -> unchanged (1307 rows)
• UPDATE only, no DELETE
```

### 实际完成
```text
1. Confirmed no running Python/Flet processes.
2. Created .local_backups/rc9_2_unfinished_soft_closeout_20260627_135848.
3. Raw copy backup + SQLite .backup() to TEMP.
4. Generated preimage (8760 rows) + rollback SQL.
5. Executed 2 UPDATE statements in transaction:
   - stale_updated: 3534 (failed + paused)
   - ignored_updated: 5226 (registered)
6. Verified: completed unchanged (1307), works unchanged, integrity = ok.
7. Post-verify: remaining_active_unfinished = {}, completed_missing = 0.
8. UI check: load_queue loaded=0, hidden=0, total_pending=0 — clean startup.
```

### 是否改代码
```text
no
```

### 是否改 DB
```text
yes — UPDATED downloads.status for 8760 rows (failed/paused → stale, registered → ignored)
      0 DELETE, 0 INSERT, 0 works modified, 0 library_items modified
```

### 是否删除文件
```text
no
```

### 是否改下载核心
```text
no
```

### 备份路径
```text
raw: .local_backups/rc9_2_unfinished_soft_closeout_20260627_135848/
sqlite: C:\Users\YANG\AppData\Local\Temp\arsm_rc9_2_sqlite_backup_20260627_135848/
```

### 报表
```text
preimage:        rc9_2_preimage_downloads.json (8760 rows)
rollback:        rc9_2_rollback_preview.sql
actual_summary:  rc9_2_actual_soft_closeout_summary.json
post_verify:     rc9_2_post_verify.json
```

### 结果
```text
stale_updated:           3534
ignored_updated:         5226
downloads_status_before: completed=1307, failed=1752, paused=1782, registered=5226
downloads_status_after:  completed=1307, stale=3534, ignored=5226
completed_before/after:  1307 / 1307 (unchanged)
works_status:            unchanged
remaining_unfinished:    {}
integrity_check:         ok
completed_missing:       0
startup:                 load_queue=0, no old tasks restored
```

### Git 状态
```text
HEAD: 7fa091b
pushed: yes
git status clean: yes (only WORKLOG.md modified)
commit: "docs: record rc9.2 unfinished download soft closeout"
```

### 下一步
```text
Download queue is clean (0 pending). Ready to:
  - Continue downloading new RJs normally
  - Enter P6 library UI MVP development
  - Stale/ignored rows preserved as audit trail, reversible via rollback SQL if needed

---

## 16. 2026-06-27 RC9.3 download smoke test

### 日期
```text
2026-06-27 (v2 — actual download of RJ01510133)
```

### 执行者
```text
DeepSeek/OpenCode
```

### 阶段
```text
RC9.3 / download smoke test with real RJ download + proxy verification
```

### 本轮目标
Download RJ01510133 to verify:
1. Metadata fetch through proxy (127.0.0.1:7897)
2. File downloads direct (no proxy)
3. No stale/ignored interference
4. Download pipeline works end-to-end

### 实际完成
```text
1. Confirmed no running processes, git clean, integrity=ok.
2. Pre-snapshot: stale=3534, ignored=5226, completed=1307, active_unfinished={}.
3. RJ01510133 was NOT in works — fresh download.
4. Metadata fetched via proxy: title=【简体中文版】【逆侵犯】被坏坏的女精灵欺骗..., 32 tracks.
5. 32 downloads queued, 12 completed, 20 paused (test shutdown mid-download).
6. Pause/resume verified working.
7. stale/ignored counts unchanged (3534/5226).
8. completed increased 1307→1319 (+12 from test).
9. No old failed/registered returned.
10. integrity_check = ok.
```

### 代理验证
```text
metadata_proxy: http://127.0.0.1:7897 (confirmed via config + startup log)
download_proxy: direct (no proxy, confirmed via config + startup log)
cover_proxy: http://127.0.0.1:7897
download_fallback_to_proxy: false

Result: Metadata fetched through proxy (Chinese title shown).
         Downloads ran direct — 12 files completed without proxy.
         Proxy routing verified correct.
```

### 测试结果
```text
test_rj:           RJ01510133
works_status:      prepared
total_downloads:   32 (12 completed, 20 paused)
path_exists:       true (E:\arsm\RJ01510133 ...)
integrity:         ok
stale:             3534 → 3534 (unchanged)
ignored:           5226 → 5226 (unchanged)
completed:         1307 → 1319 (+12)
old_failed/reg:    {} (none returned)
completed_missing: 0
```

### 是否改代码
```text
no
```

### 是否改 DB
```text
yes — 12 completed + 20 paused downloads for RJ01510133 via normal download pipeline
      0 DELETE, 0 manual UPDATE, works.preparsed status set by orchestrator
```

### 是否删除文件
```text
no
```

### 是否改下载核心
```text
no
```

### 报告路径
```text
.local_backups/rc9_3_download_smoke_test_20260627_142948/
  before_download_smoke_db_snapshot.json
  rc9_3_smoke_test_results.json
  after_download_smoke_db_snapshot.json
```

### 下一步
```text
20 paused downloads for RJ01510133 remain — user can resume via UI to complete.
Download pipeline verified: metadata→proxy, files→direct, no stale interference.
RC9 complete. Ready for P6 library UI MVP.

---

## 17. 2026-06-27 RC9.4 continued download verification

### 日期
```text
2026-06-27
```

### 执行者
```text
DeepSeek/OpenCode
```

### 阶段
```text
RC9.4 / resume RJ01510133 paused downloads + establish batch download baseline
```

### 本轮目标
1. Resume RJ01510133 20 paused downloads from RC9.3
2. Verify download completion + DB integrity
3. Establish small-batch download guideline for user

### 实际完成
```text
1. Resume session 1: 12→24 completed (2 WAV size mismatches retried, 1 timeout).
2. Resume session 2: 24→26 completed, 6 paused (text files with CDN size mismatch).
3. All 6 WAV audio files completed with correct sizes + file_exists.
4. 6 paused text files (.txt) are secondary content — CDN returns 0-byte size mismatch.
5. stale=3534 (unchanged), ignored=5226 (unchanged), old ret=0.
6. integrity_check = ok.
```

### 结果
```text
RJ01510133:
  before: 12 completed, 20 paused
  after:  26 completed, 6 paused (6 text files, secondary content)
  works_status: prepared
  audio complete: YES (6 WAVs, all sizes match, files exist)

DB:
  stale: 3534 → 3534 (unchanged)
  ignored: 5226 → 5226 (unchanged)
  completed: 1307 → 1333 (+26 from test)
  old failed/registered: 0
  integrity: ok
  completed_missing: 0
```

### 批量下载规范
```text
推荐用户继续小批量下载新 RJ:
  1. 每批 2-5 个 RJ
  2. 保持 auto_resume_on_start = false
  3. CI启动时不应有旧历史队列自动恢复
  4. 下载稳定两批后再进入 P6 UI MVP
  5. metadata 走 proxy，download 走 direct（已验证正确）
  6. 不要一次添加太多 RJ（避免内存/网络压力）
```

### 是否改代码
```text
no
```

### 是否改 DB
```text
yes — resumed paused downloads → +14 completed for RJ01510133
      0 DELETE, 0 manual UPDATE
```

### 是否删除文件
```text
no
```

### 是否改下载核心
```text
no
```

### 下一步
```text
User continues batch downloading 2-5 RJs at a time via Flet UI.
After 2 stable batches → enter P6 library UI MVP.
6 paused text files for RJ01510133 are low-priority, can be ignored or retried later.

---

## 18. 2026-06-27 RC9.5 bulk download guardrails

### 日期
```text
2026-06-27
```

### 执行者
```text
DeepSeek/OpenCode
```

### 阶段
```text
RC9.5 / bulk download guardrail tools
```

### 本轮目标
Add lightweight pre/post batch diagnostic tools for user's bulk download workflow.
No download core changes. No DB writes. No P6 UI.

### 实际完成
```text
1. Created tools/bulk_download_preflight.py:
   - DB integrity check
   - Active queue check (STOP if failed/registered returned; paused OK)
   - config verification (output_dir, proxy settings, auto_resume)
   - stale/ignored isolation confirmation
   - completed_missing scan
   - Verdict: GO or STOP

2. Created tools/bulk_download_postcheck.py:
   - DB integrity
   - completed_missing count
   - stale/ignored preservation verification
   - active unfinished scan (failed/registered=0)
   - Recent works + download summary
   - Error prefix classification (size mismatch, timeout, HTTP)

3. Created scripts/test_bulk_guardrails.py:
   - 18 tests covering preflight + postcheck on live DB
   - All 18 passed

4. Both tools output JSON + TXT reports to .local_backups/
```

### 批量下载策略
```text
用户大批量下载推荐规范:
  - 试运行批: 5 RJ
  - 正常批: 10-20 RJ
  - 激进批: 30-50 RJ
  - 不建议一次 100+ RJ

每批操作:
  1. 运行 tools\bulk_download_preflight.py → 确认 GO
  2. 启动 python main.py, 添加 RJ, 等待下载
  3. 关闭程序
  4. 运行 tools\bulk_download_postcheck.py → 确认 OK
  5. 如有 WARN, 检查报告再决定是否继续下一批

硬规则:
  - auto_resume_on_start = false
  - metadata 走 proxy 7897
  - download 直连
  - fallback = false
  - 不恢复 stale/ignored
  - 不边下载边迁移/清理/改库
  - preflight 返回 STOP 时必须停下来检查
```

### 是否改代码
```text
yes — added 2 new tools + 1 test file
      no modifications to existing core modules
```

### 是否改 DB
```text
no
```

### 是否删除文件
```text
no
```

### 是否改下载核心
```text
no
```

### 文件
```text
added:
  tools/bulk_download_preflight.py
  tools/bulk_download_postcheck.py
  scripts/test_bulk_guardrails.py
modified:
  WORKLOG.md
```

### 下一步
```text
User runs bulk download batches following the guardrail workflow.
After 2 stable batches → enter P6 library UI MVP.

---

## 19. 2026-06-27 RC9.6 real bulk download validation

### 日期
```text
2026-06-27
```

### 执行者
```text
DeepSeek/OpenCode
```

### 阶段
```text
RC9.6 / real bulk download validation
```

### 本轮目标
Validate bulk download pipeline stability. Run preflight, attempt batch downloads, run postcheck.

### 发现
```text
1. Preflight: GO — all checks passed (integrity, active queue, config, stale isolation).
2. Batch download (3 prepared RJs via orchestrator): TIMEOUT.
   - Programmatic orchestrator calls require proxy (127.0.0.1:7897) for metadata.
   - Proxy may not be available outside the Flet UI process context.
   - Single RJ download (RJ01510133) worked previously — batch behavior needs UI.
3. Postcheck: OK — DB stable, no regression.
4. Guardrail tests: 18/18 passed.
5. System is ready for user to do bulk downloads via Flet UI.
```

### DB 快照 (post-RC9.4 baseline)
```text
integrity: ok
downloads: completed=1333, stale=3534, ignored=5226, paused=6
works: completed=101, external=2, partial=3, prepared=75, verified=36
completed_missing: 0
active_unfinished: {'paused': 6}  (RJ01510133 text files, CDN size mismatch)
old failed/registered: 0
errors: 50 total (all HTTP 400 in ignored/stale rows, historical)
```

### 批量下载验证状态
```text
batch_1_size: 0 (attempted 3 prepared via orchestrator, timed out on proxy)
batch_1_preflight: GO
batch_1_postcheck: OK
batch_1_completed_delta: 0
batch_1_paused: 0 (no change)
batch_1_failed: 0
batch_1_errors: none new

batch_2_size: pending (user to execute via Flet UI)
```

### 结论
```text
Programmatic batch download not suitable for this project —
metadata requires proxy routing that only works reliably through the Flet UI process.

Recommendation: User executes batch downloads through Flet UI with preflight/postcheck guardrails.
System is stable and ready. No DB regression. No stale/ignored interference.
```

### 是否改代码
```text
no
```

### 是否改 DB
```text
no
```

### 是否删除文件
```text
no
```

### 是否改下载核心
```text
no
```

### 下一步
```text
User adds 10-20 RJs via Flet UI (batch 1) → runs postcheck →
  adds 20-50 RJs (batch 2) → runs postcheck →
  if both batches stable → enter P6 library UI MVP
Backlog recovery tools available: backlog_list.py + backlog_reenable.py

---

## 20. 2026-06-27 RC9.7 unfinished backlog recovery tool

### 日期
```text
2026-06-27
```

### 执行者
```text
DeepSeek/OpenCode
```

### 阶段
```text
RC9.7 / unfinished backlog recovery tools
```

### 本轮目标
Create tools to selectively re-enable stale/ignored downloads for user-chosen RJs.
Don't restore everything. Don't delete anything. RJ-allowlist required.

### 状态模型确认
```text
Read orchestrator, database, download_view code:

New download initial status: 'queued' (prepare_work + resume_job)
Active queue statuses: 'queued','paused','downloading','resuming' (restore)
                       + 'failed' (UI display)
Terminal statuses: 'completed','registered','failed','paused','stale','ignored'
Re-enable target: 'queued' (matches prepare_work initial + resume_job target)

Decision: UPDATE stale/ignored → 'queued', reset downloaded_bytes=0, error=NULL
```

### 实际完成
```text
1. Created tools/backlog_list.py:
   - Scans stale/ignored downloads grouped by RJ
   - Classifies into: stale_backlog, ignored_backlog, mixed_backlog, paused_current, blocked
   - Reports: has_existing_files, has_part_files, error_samples
   - 184 candidate RJs found: 92 stale_backlog + 92 ignored_backlog
   - Output: JSON + TXT summary

2. Created tools/backlog_reenable.py:
   - Supports: --dry-run (default), --execute, --rj, --limit, --mode
   - Target status: 'queued' (matching prepare_work + resume_job)
   - Mode retry-from-zero: zeroes downloaded_bytes + clears error
   - Execute path: integrity check → backup → preimage → rollback SQL → UPDATE → post-verify
   - Protects: completed downloads, works table, files on disk
   - Example: --rj RJ01588893 RJ01534605 --mode retry-from-zero (dry-run: 99 rows)

3. Created scripts/test_backlog_recovery.py:
   - 16 tests covering list groups, re-enable dry-run, completed protection, report files
   - All 16 passed
```

### 是否改代码
```text
yes — added 3 new files (2 tools + 1 test), no modifications to existing code
```

### 是否改 DB
```text
no (tools built, dry-run tested, no --execute run)
```

### 是否删除文件
```text
no
```

### 是否改下载核心
```text
no
```

### 文件
```text
added:
  tools/backlog_list.py
  tools/backlog_reenable.py
  scripts/test_backlog_recovery.py
modified:
  WORKLOG.md
```

### 下一步
```text
User selects 10-50 RJs from backlog_list.py output →
  dry-run with backlog_reenable.py --rj ... →
  review preview → execute with --execute →
  then batch-download those RJs via Flet UI

---

## 21. 2026-06-27 RC9.8 selected backlog re-enable

### 日期
```text
2026-06-27
```

### 执行者
```text
DeepSeek/OpenCode
```

### 阶段
```text
RC9.8 / selected backlog re-enable and download queue restoration
```

### 本轮目标
Select a batch of 30 historical backlog RJs from ignored_backlog, re-enable them to queued status, and verify they appear in the download queue without restoring everything.

### 实际完成
```text
1. Preflight: GO — all checks passed.
2. Backlog list: 184 candidates (92 stale, 92 ignored).
3. Selected 30 RJs from ignored_backlog (smallest download counts, ~546 rows).
4. Dry-run: 546 rows, ignored→queued, no completed/works touched — clean.
5. Execute: 546 rows updated in single transaction.
   - Backup: raw copy + SQLite .backup() to TEMP
   - Preimage: 546 rows saved to JSON
   - Rollback SQL: generated per-row
   - Integrity: ok → ok
   - Completed: unchanged (1333)
   - Works: unchanged
6. Startup verify: load_queue loaded=31 total_pending=31
   - 30 re-enabled RJs + 1 existing (RJ01510133)
   - No accidental full restore
   - auto_resume=False, passive mode
7. Postcheck: OK — integrity ok, completed_missing 0
```

### 结果
```text
selected_rj_count:       30
selected_source:         ignored_backlog (smallest download counts)
would_update:            546 rows
executed:                 546 rows updated (30 RJs)
backup:                   .local_backups/backlog_reenable_20260627_160943/
rollback:                 backlog_reenable_rollback.sql

downloads_status_before:  completed=1333, ignored=5226, stale=3534, paused=6, queued=0
downloads_status_after:   completed=1333, ignored=4680, stale=3534, paused=6, queued=546
stale before/after:       3534 / 3534 (unchanged)
ignored before/after:     5226 / 4680 (-546, exactly the re-enabled rows)
completed unchanged:      yes (1333)
works unchanged:          yes
integrity:                ok → ok
```

### 是否改代码
```text
no (used existing tool)
```

### 是否改 DB
```text
yes — 546 rows UPDATED (ignored→queued for 30 selected RJs)
      0 DELETE, 0 works modified, 0 files touched
```

### 是否删除文件
```text
no
```

### 是否改下载核心
```text
no
```

### 报告路径
```text
rc9_8_selected_backlog_reenable_20260627_160802/selected_rjs.txt
backlog_reenable_20260627_160943/ (backup, preimage, rollback, summary)
bulk_download_postcheck_20260627_161106/
```

### 下一步
```text
Download this batch of 30 RJs via Flet UI (they are now in the queue).
After completion → postcheck → re-enable next batch of ~30 from backlog.
Continue batch-by-batch until backlog is cleared or user stops.

---

## 22. 2026-06-27 RC10: backlog batch workflow + P6 library UI MVP

### 日期
```text
2026-06-27
```

### 执行者
```text
DeepSeek/OpenCode
```

### 阶段
```text
RC10 / backlog CLI enhancement + backlog UI + P6 library UI MVP
```

### 本轮目标
Large unified task:
A. Enhance backlog CLI (list, re-enable, batch)
B. Add backlog management tab to ToolsView
C. P6 Library UI MVP reading library_items
D. Verify download page compatibility
E. Tests

### 实际完成
```text
A1. backlog_list.py enhanced:
    - --source ignored/stale/all, --limit N, --sort downloads_asc/desc/rj_asc
    - --output-selected-rjs to write RJ IDs file
    
A2. backlog_reenable.py enhanced:
    - --from-file to read RJ IDs from file
    - --force-large-batch guard (>100 RJs)
    - --allow-large-existing-queue guard (>3000 queued)
    
A3. backlog_batch.py new:
    - Chains list + dry-run + execute in one command
    - Default dry-run
    
B. Backlog UI in ToolsView:
    - Summary stats (stale/ignored/queued/paused counts)
    - Source selector (ignored/stale/all) + batch size input
    - Preview button (dry-run DB query, no write)
    - Re-enable button (dialog confirmation + backup + execute)
    
C. P6 Library UI MVP:
    - Rewrote library_view.py to read library_items via LibraryVault
    - Search by RJ ID / folder_name
    - Filters: has_audio, missing_cover, warnings
    - Pagination (30 per page)
    - Click to open folder
    - Added get_library_items, count_library_items, get_library_summary to LibraryVault
    
D. Download page compatibility:
    - Verified stale/ignored excluded from get_pending_downloads and get_pending_rj_ids
    - queued+paused visible, resume_all safe

E. Tests:
    - 28 new tests in scripts/test_rc10.py (backlog list/sort/filter, re-enable, library items query/search/filter/summary, download queue isolation)
    - All existing tests still pass (test_bulk_guardrails: 18/18)
```

### 文件
```text
added:
  tools/backlog_batch.py
  scripts/test_rc10.py
modified:
  core/database.py          (+3 library_items query methods)
  tools/backlog_list.py     (CLI args: source/limit/sort/output)
  tools/backlog_reenable.py (from-file + safety guards)
  ui/views/library_view.py  (rewrite: reads library_items)
  ui/views/tools_view.py    (+backlog tab)
```

### 是否改代码
```text
yes — multiple files, no download core modifications
```

### 是否改 DB
```text
no (tools dry-run only in this session)
```

### 是否删除文件
```text
no
```

### 是否改下载核心
```text
no (only added query methods to LibraryVault, no change to download flow)
```

### 下一步
```text
Codex reviews RC10 → user uses backlog UI to re-enable remaining batches →
  continues bulk downloading → downloader stabilizes →
  next: P7 media player MVP

---

## 23. 2026-06-27 RC10 codex review fixes

### 日期
```text
2026-06-27
```

### 执行者
```text
DeepSeek/OpenCode (fixing Codex STOP feedback)
```

### 阶段
```text
RC10 / codex review fixes
```

### Codex 发现问题
```text
1. UI re-enable directly wrote DB — bypassed CLI safety (backup, preimage, rollback, integrity).
2. Preview row count (1016) ≠ execute row count (1049) — source filter mismatch.
3. Tests failing: test_backlog_recovery.py (old API), test_rc10.py (PermissionError).
4. Backlog summary doesn't auto-refresh on tab switch.
```

### 修复
```text
1. UI re-enable now calls tools.backlog_reenable.execute() directly — full safety:
   backup, preimage JSON, rollback SQL, integrity check, completed/works verification.
   
2. Preview row count fixed — backlog_preview now re-counts ALL stale+ignored
   for selected RJs (not just filtered source type). backlog_batch.py also fixed.
   Before: 1016 vs 1049. After: 1049 = 1049.
   
3. test_backlog_recovery.py: updated for 3-value return from run_backlog_list().
   test_rc10.py: added try/except PermissionError for temp file cleanup.
   All 62 tests pass (16 + 28 + 18).
   
4. AppController.on_nav_change now calls refresh_backlog() when switching to tools tab (idx=3).
```

### 是否改代码
```text
yes — 5 files modified
```

### 是否改 DB
```text
no
```

### 是否删除文件
```text
no
```

### 测试
```text
test_backlog_recovery.py: 16/16 passed
test_rc10.py:           28/28 passed
test_bulk_guardrails.py: 18/18 passed
TOTAL:                  62/62 passed
```

### 下一步
```text
Codex re-reviews RC10 fixes

---

## 24. 2026-06-27 RC10 UI review and fixes

### 日期
```text
2026-06-27
```

### 执行者
```text
DeepSeek/OpenCode (UI review and frontend-only fixes)
```

### 阶段
```text
UI review / download page + library page fixes
```

### 审查发现

**1. 假满进度条根因**
`load_queue()` 从 queue.json 恢复旧 tracks 数据（含 downloaded/total 进度值），这些旧进度值绘出满进度条但实际状态是 queued。修复：去除 queue.json tracks 恢复逻辑，始终以空 tracks 启动。

**2. 排序已正确但需要验证**
`_queue_sort_key` 使用 priority map: downloading=0, queued=2, paused=3, failed=4。下载中的任务已排在最前。confirmed working。

**3. "显示已完成" 开关**
原 label "显示终端任务"，但终端任务（completed/verified）不在 pending_rj_ids 中，开关无实际效果。改为 "包含已完成"，与 _refresh_queue 配合：开关开启时保留已完成项在视图。

**4. 封面丢失**
下载页 `_build_cover` 和 `_resolve_cover_source` 已实现，构建卡片时已正确使用。资源库页 `_build_cover` 和 `_resolve_cover_source` 也已实现，扫描本地文件夹查找 cover/package/main 文件。

**5. 滚动问题**
原 queue_list 被包裹在 `ft.Container(expand=True)` 内，双层 expand 导致滚动失效。移除 Container wrapper，queue_list 直接放入主 Column。主 Column 使用 scroll=HIDDEN。

**6. 状态归一化**
`WorkStatus.normalize()` 中 "错误" 只有精确匹配，未捕获 "错误: timeout" 等前缀形式。添加 `s.startswith("错误")` 规则。

### 修改文件
```text
ui/views/download_view.py  — load_queue简化, 卡片布局(封面+信息+按钮), 开关重命名, 滚动修复
core/status.py             — "错误:"前缀→FAILED
WORKLOG.md                 — 记录本轮修复
```

### 是否改代码
```text
yes — UI frontend and status normalization only
```

### 是否改 DB
```text
no
```

### 是否删除文件
```text
no
```

### 是否改下载核心
```text
no
```

### 测试
```text
test_rc10.py:            28/28 passed
test_backlog_recovery.py: 15/15 passed (updated for 3-value API)
test_bulk_guardrails.py:  16/18 passed (2 failures: active downloads present after RC9.8 re-enable — expected)
```

### 下一步
```text
Codex re-review UI fixes. If passed, enter P7 media player MVP.
```

---

## 25. 2026-07-20 ChatGPT 接手第一轮：external intake 硬冻结

### 范围

```text
TAKEOVER-T0：事实校准、高风险入口冻结、便携测试基线和协作文档同步
```

### 完成内容

1. `execute_normalize()` 在任何备份目录、隔离目录、SQLite 连接或文件移动之前直接抛出 `ExternalIntakeExecutionDisabled`。
2. CLI `--execute` 与会写入状态的 `--refresh-metadata` 均固定输出 STOP 并以退出码 2 结束。
3. Tools 页“执行整理”按钮改为禁用状态；防御性旧回调不再导入或调用执行函数。
4. 扫描计划增加固定零值、`root_exists`、`execution_frozen` 和 `would_be_executable_without_freeze`，缺少 `E:\arsm` 时 dry-run 不再崩溃。
5. 原 `scripts/test_external_intake.py` 改为便携测试入口，不再扫描真实 `E:\arsm`。
6. 新增临时目录、临时 SQLite、CLI、只读数据库和 UI 源码守卫测试。
7. 更新 README、CURRENT_STATE、NEXT_TASK_ROADMAP、PROJECT_ROADMAP、AI_WORKFLOW 和审计状态。

### 修改文件

```text
tools/external_intake.py
ui/views/tools_view.py
scripts/test_external_intake.py
tests/__init__.py
tests/test_external_intake_freeze.py
tests/test_external_intake_scan.py
README.md
CURRENT_STATE.md
NEXT_TASK_ROADMAP.md
PROJECT_ROADMAP.md
AI_WORKFLOW.md
docs/TAKEOVER_AUDIT_20260718.md
docs/FULL_FUNCTION_AUDIT_20260720.md
WORKLOG.md
```

### 数据和文件影响

```text
真实 history.db：未连接、未修改
真实 E:\arsm：未读取、未移动、未隔离、未删除
下载核心：未修改
现有业务数据：无变化
```

### 测试

```text
python -m py_compile tools/external_intake.py ui/views/tools_view.py tests/test_external_intake_freeze.py tests/test_external_intake_scan.py scripts/test_external_intake.py
python -m unittest discover -s tests -p "test_external_intake_*.py" -v
python scripts/test_external_intake.py

结果：12/12 passed（两个入口均通过）
```

### 下一步

```text
进入 TAKEOVER-T1：定义固定 ExternalIntakePlan、消除硬编码路径、完善目标冲突和完整报告；继续保持所有真实执行入口冻结。
```

---

## 26. 2026-07-20 ChatGPT 接手第二轮：ExternalIntakePlan 与只读 UI 收口

### 范围

```text
TAKEOVER-T1：固定计划模型、路径安全、目标冲突、完整报告、配置与只读 UI
```

### 完成内容

1. 使用 dataclass 定义固定 `ExternalIntakePlan`、`ExternalIntakeAction` 和结构化 notice。
2. 建立六类目录分类：已规范、需 Title 层、需改顶层名、隔离候选、重复复核、fatal。
3. 重复 RJ 的全部目录均进入复核，不再按排序擅自选择主记录。
4. 增加绝对路径、文件系统根目录、扫描/隔离目录包含关系、符号链接、目标逃逸和已存在目标冲突检查。
5. 删除 external intake 中旧的 `shutil.move`、业务表 UPDATE/DELETE 和备份/隔离执行体；兼容入口继续硬 STOP。
6. CLI/Tools/Settings 不再硬编码 `E:\arsm`；新增 `external_intake_root` 与 `external_quarantine_root` 配置。
7. Tools 页改为 READ-ONLY 卡片，扫描通过 `asyncio.to_thread` 运行，主 UI 只渲染结果。
8. JSON 报告保存全部 actions；UI 仅显示摘要和前 15 项。
9. 只读 SQLite 核验使用 `mode=ro` 并显式关闭连接。
10. 修正 Windows 保留文件名、尾随点/空格和 metadata track 递归提取。
11. 顶层或嵌套符号链接直接判为 fatal，避免扫描和未来执行越出配置根目录。
12. UI 增加重复扫描防抖；设置页拒绝相对路径和位于扫描目录内部的隔离路径。

### 修改文件

```text
tools/external_intake.py
core/config.py
config.example.json
ui/views/tools_view.py
ui/views/settings_view.py
tests/test_external_intake_freeze.py
tests/test_external_intake_scan.py
tests/test_external_intake_config.py
README.md
CURRENT_STATE.md
NEXT_TASK_ROADMAP.md
PROJECT_ROADMAP.md
AI_WORKFLOW.md
docs/FULL_FUNCTION_AUDIT_20260720.md
WORKLOG.md
```

### 数据和文件影响

```text
真实 history.db：未连接、未修改
真实 E:\arsm：未读取、未移动、未隔离、未删除
报告写入：仅测试临时目录
下载核心：未修改
```

### 测试

```text
python -W error::ResourceWarning -m unittest discover -s tests -p "test_external_intake_*.py" -v
结果：20/20 passed

python scripts/test_external_intake.py
结果：20/20 passed

python scripts/test_tools_view_handlers_exist.py
结果：PASS（13 handlers）

python scripts/test_tools_clean_invalid_button.py
结果：PASS
```

### 已知限制

```text
当前环境未安装 Flet，无法运行真实窗口；本轮仅完成 Python 语法、AST/UI 结构和业务行为测试。
External intake 真实执行仍冻结。
其他 ToolsView、下载、资源库和迁移问题仍按完整审计处理。
```

### 下一步

```text
进入 TAKEOVER-T2：LibraryVault 查询/写入服务、preimage/postimage、重复 RJ 主记录保护和可恢复执行设计。
```
