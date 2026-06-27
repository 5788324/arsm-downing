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
```
