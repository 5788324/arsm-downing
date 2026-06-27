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
