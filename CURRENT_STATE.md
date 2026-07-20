# CURRENT_STATE.md

# arsm-downing / arsm-suite 当前状态

> 更新时间：2026-07-20
> 接手分支：`chatgpt/takeover-20260718`
> 基线提交：`1f33595b8fb3e7d895ae6bca1f907186d836bc60`

## 1. 项目定位

本项目是一个仅供个人本地使用的 Windows ASMR/RJ 媒体库工具，继续保持为单一桌面应用，不拆分成多个项目。

目标能力：

- ASMR.one 作品下载与断点续传
- SQLite 下载状态与资源库数据管理
- 本地资源库扫描、检索、异常识别和目录整理
- 外部资源接入、元数据刷新、完整性核验与隔离
- 后续增加本地音频播放器

当前技术栈：

```text
Python + Flet + SQLite + asyncio + aiohttp + pathlib/os
```

主入口：

```text
main.py -> ui.app.start_app
```

## 2. 必须保持的架构约束

```text
history.db / SQLite = 唯一业务真源
LibraryVault = 唯一正式数据库访问入口
UI 不得直接 sqlite3.connect()
扫描 JSON / manifest 不得成为 UI 主数据源
P4 下载状态修复与 P5 资源库索引写入不得混在一次操作中
所有文件移动、隔离、删除必须先 dry-run，并具有可验证回滚信息
```

## 3. 已实现功能

仓库当前已经包含：

- 下载队列、暂停、恢复、失败重试、速度统计
- 元数据缓存与三通道代理配置
- `works`、`downloads`、`library_items`、`library_index` 等 SQLite 数据层
- 资源库卡片、搜索、过滤、分页与异常视图
- Dashboard 数据库统计
- 迁移 dry-run / execute / verify
- backlog 预览与重新启用工具
- 外部资源目录扫描、目录规范化、隔离、元数据刷新和文件列表核验代码
- 大量脚本式回归测试

## 4. 仓库状态

### 4.1 GitHub 状态

- 默认分支：`main`
- 当前接手基线：`1f33595`
- 接手前没有开放的 Pull Request
- 接手前没有 Issue 任务台账
- 尚未建立标准 GitHub Actions CI
- 历史开发主要直接提交到 `main`

接手后规则：

```text
main 仅接收审查通过的 PR
开发使用 chatgpt/* 分支
每轮改动必须同步 CURRENT_STATE / WORKLOG / 路线图
高风险写入必须独立 PR，不与 UI 功能混合
```

### 4.2 最近代码阶段

`TAKEOVER-T0/T1/T2/T3` 已完成 external intake 的冻结、只读计划、数据库服务和沙盒文件事务收口：

- 固定 `ExternalIntakePlan` schema v3、六类目录分类、manifest token 和完整逐文件映射
- 扫描根目录、隔离目录改为配置项
- 重复 RJ 全部标记 `duplicate_review`
- 目标路径冲突、危险根目录、符号链接升级为 fatal
- Tools 页通过后台线程扫描，并复用 AppController 的唯一 `LibraryVault`
- 计划附加 DB preimage token、主记录路径、pending 和资源库路径上下文
- `LibraryVault` 支持显式临时数据库与真正 `mode=ro` 只读打开
- 新增统一路径事务，同步 `works`、`downloads`、`library_items`、`library_index`
- 成功返回 preimage/postimage；SQLite 失败整事务 rollback 并保留 preimage
- 重复副本不能按 RJ 号覆盖正常主记录
- 全新数据库现在会创建 `library_items` 基础 schema
- 新增 staging/rollback/Journal 状态机，只在显式 sandbox 内执行
- staging 与目标按相对路径、数量、大小和关键哈希双重校验
- Title 层文件映射与 downloads.local_path 使用同一映射更新
- DB 失败自动恢复原源目录；进程提交前后中断可按 Journal 恢复

真实资源库移动、隔离、元数据刷新和 UI/CLI 执行入口继续保持冻结。文件执行状态机已在 tempfile 沙盒中完成，但尚未经过 Windows 文件锁、真实路径和复制资源库验收。

## 5. 最近一次已记录的本机状态

`docs/CURRENT_FUNCTIONS_REVIEW_20260628.md` 记录的 2026-06-28 本机快照为：

```text
主资源库：E:\arsm
works = 184
library_items = 184
library_index = 184
downloads = 0
warnings = 0
non_verified = 0
PRAGMA integrity_check = ok
```

这些数值只代表 2026-06-28 的历史快照。接手后不得把它们当作 2026-07-18 的实时状态；需要 Codex 在用户 Windows 本机重新执行只读核验后才能更新。

## 6. 当前已确认问题

### P0 / 必须先修

1. external intake 沙盒事务已完成，但尚未通过 Windows/T6 复制资源库执行验收，真实执行继续冻结。
2. `needs_title_layer` 仍缺少基于 metadata title 的无歧义目标命名；当前不允许执行。
3. 下载核心仍存在 HTTP 416、`.part` 进度、取消/恢复和响应清理问题。
4. 资源库递归验证、扫描快照、缓存恢复和旧索引清理仍未完成。
5. Windows/Flet/真实目录只读验收尚未执行。

### P1 / 接手后尽快修

1. `PROJECT_ROADMAP.md` 仍包含历史阶段内容，当前执行以 `NEXT_TASK_ROADMAP.md` 为准。
2. 依赖未锁版本，尚未建立项目级统一 pytest 和 CI。
3. ToolsView 包含较多同步文件/DB 操作，可能阻塞 Flet UI。
4. 下载、资源库、迁移和 backlog 仍有完整功能审计中记录的 P0/P1 问题。

## 7. 当前禁止事项

在 P0 修复完成并通过本机 dry-run 前，不执行：

```text
python tools/external_intake.py --execute --confirm-bulk
Tools -> External Intake -> Execute
批量移动 E:\arsm 目录
批量隔离目录
通过 external_intake 直接修改 works/library_items/library_index
```

允许：

```text
只读代码审计
使用临时目录的纯扫描测试
不连接真实 history.db 的单元测试
读取 GitHub 文档和提交历史
在接手分支修改代码与文档
```

## 8. 当前阶段

```text
TAKEOVER-T0：已完成——事实校准、核心/CLI/UI 硬冻结
TAKEOVER-T1：已完成——固定计划模型、路径配置、冲突分类、完整报告和后台 UI 扫描
TAKEOVER-T2：已完成——LibraryVault 快照、四表路径事务、preimage/postimage 与重复 RJ 保护
TAKEOVER-T3：已完成——逐文件映射、staging、双重校验、Journal、回滚与崩溃恢复
TAKEOVER-T4：下一步——统一 pytest、依赖锁定和 CI
TAKEOVER-T5：Windows 本机只读 dry-run 验收
TAKEOVER-T6：沙盒执行验收
```

## 8.1 当前验证结果

```text
python -W error::ResourceWarning -m unittest discover -s tests -p "test_external_intake_*.py" -v
结果：62/62 passed
完整报告 60 actions 不截断：通过
重复 RJ 全候选复核和主记录保护：通过
四表路径事务与 preimage/postimage：通过
沙盒 staging/Title 映射/关键哈希：通过
DB 失败文件恢复与崩溃 Journal 恢复：通过
批次失败立即停止：通过
SQLite 注入失败全事务回滚：通过
只读 CLI 数据库哈希不变：通过
目标冲突与危险路径：通过
配置保存/读取：通过
真实 history.db：未连接
真实 E:\arsm：未读取或修改
真实文件移动/删除：无
```

详细任务见 `NEXT_TASK_ROADMAP.md`。

## 9. AI 协作分工

```text
ChatGPT：主要开发、架构、代码审查、Git/PR、可在当前环境完成的测试、文档维护
Codex：仅负责用户 Windows 本机、Flet GUI、真实 E:\arsm/history.db、部署与实机验收
DeepSeek/OpenCode：仅在明确分配时承担低风险、大批量实现，不再作为默认项目管理者
用户：只做最终需求决策，不承担日常代码测试
```

## 10. 当前接手结论

```text
项目可继续维护，不需要推倒重写。
下载器、SQLite 数据层和资源库 UI 已形成较完整基础。
当前优先级不是播放器，而是收口 external intake 的文件/DB 安全边界、建立可重复测试与恢复可信文档。
```
