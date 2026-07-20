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
- 已在接手分支建立 GitHub Actions portable test gate；尚未推送，因此远端 CI 尚未实际运行
- 历史开发主要直接提交到 `main`

接手后规则：

```text
main 仅接收审查通过的 PR
开发使用 chatgpt/* 分支
每轮改动必须同步 CURRENT_STATE / WORKLOG / 路线图
高风险写入必须独立 PR，不与 UI 功能混合
```

### 4.2 最近代码阶段

`TAKEOVER-T0~T6` 已完成 external intake 安全收口、文件事务沙盒验收和便携测试门建设；`TAKEOVER-T5A/T5C` 已完成下载核心及资源库 UI 的代码级收口；`TAKEOVER-T8A` 已完成迁移模块重构：

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
- 新增统一 `python -m pytest` 测试门、Linux/Windows CI 定义和精确依赖兼容集
- 默认测试在工作区发现 `history.db`、`config.json` 或 `queue.json` 时 fail-closed
- 新增在线 SQLite 只读快照和 manifest 校验，可在下载器持续运行时生成一致性副本
- 新增快照状态报告，统计 completed/failed/paused/queued/downloading 等混合任务
- 下载响应改为显式 200/206/416 计划，严格校验 Range、大小和本地断点
- 取消/失败记录真实 `.part` 大小；重连、批量控制和 UI 更新分离到正确线程
- 过期 metadata cache 只在恢复/离线 fallback 路径显式允许，保护长期暂停任务
- 设置页写入真实 work/file concurrency；强制重复和 canonical directory 行为已修正
- 新增本地 ASMR.one 兼容服务器、真实 aiohttp Range 集成和隔离 Flet UI 启动器
- 资源库 UI 移除 E 盘、用户名、假 RJ 和固定统计；搜索实际传入 SQLite，路径诊断在后台线程执行
- 新增 Windows 一键验收器，集中输出 portable、snapshot、live download 和 UI evidence
- 新增 T6 复制资源库沙盒验收：正常改名、Title 层复核、重复 RJ、空目录、`.part`、DB 失败和提交后恢复均有真实目录证据
- Tools 维护操作改为独立连接和后台执行：队列清理只读预览、缓存安全清理、活跃任务阻止 VACUUM
- backlog 预览不再硬编码排除特定 RJ；执行要求运行时完全空闲，默认保留断点并生成 online backup/preimage/rollback SQL
- 迁移候选使用磁盘 manifest 实测文件数/大小，不再信任可能过期的 `works.size_bytes`
- 迁移递归拒绝 `.part` 和 symlink，按完整相对路径、逐文件大小和哈希验证 staging/target
- 迁移通过统一事务同步四表；源删除失败会验证源完整性后回滚，部分删除固定 `stop_required`
- Tools 迁移按钮改为后台只读计划，目标目录存在时不再删除；迁移沙盒验收 10/10 PASS

真实资源库移动、隔离、元数据刷新和 UI/CLI 执行入口继续保持冻结。文件执行状态机已通过 Linux/tempfile 复制资源库验收，但尚未经过 Windows 文件锁、长路径、杀毒软件和真实资源库验收。

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

这些数值只代表 2026-06-28 的历史快照，不能代表当前状态。用户已确认当前仍有 100 多个任务处于 completed/failed/paused/queued/downloading 等混合状态。后续只通过 SQLite 在线备份生成的 manifest-verified 快照核验，不直接维护活跃数据库。

## 6. 当前已确认问题

### P0 / 必须先修

1. T6 复制资源库沙盒事务已通过，但 Windows 文件锁、长路径和真实资源库 T7 验收尚未执行，真实入口继续冻结。
2. `needs_title_layer` 仍缺少基于 metadata title 的无歧义目标命名；当前不允许执行。
3. 下载核心的 416、Range、`.part` 和主要暂停/恢复语义已完成代码级修复，但真实 ASMR.one/Windows UI 尚未验收。
4. LibraryView 的搜索、硬编码路径、后台加载和异常显示已修；资源库扫描快照写入、旧索引清理仍未完成。
5. 用户当前仍有 100 多个混合状态任务，真实 backlog 恢复、VACUUM、队列删除和 T7 目录整理不得执行。

### P1 / 接手后尽快修

1. `PROJECT_ROADMAP.md` 仍包含历史阶段内容，当前执行以 `NEXT_TASK_ROADMAP.md` 为准。
2. GitHub Actions 已在本地分支建立，但在最终推送前尚未由远端 Runner 验证 Python 3.10/Linux 与 Python 3.12/Windows。
3. ToolsView 的缓存、VACUUM、队列预览、网络诊断、backlog 和迁移 dry-run/verify 已后台化；兼容资源库 rebuild 仍需继续审计。
4. 迁移代码级风险已在 T8A 收口，但 Windows 文件锁、长路径和真实小批量证据仍未完成。

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
TAKEOVER-T4：已完成——统一 pytest、依赖锁定、CI 定义、在线 DB 快照与验收规范
TAKEOVER-T5A：已完成——下载响应、断点恢复、镜像切换、UI 控制语义和隔离 smoke 工具
TAKEOVER-T5B：验收包已完成——等待 Codex 在 Windows 执行在线快照、真实小样本和视觉验收
TAKEOVER-T5C：已完成——资源库搜索、后台加载、异常分类和动态统计代码级收口
TAKEOVER-T6：已完成——复制资源库执行、幂等、DB 失败回滚和提交后恢复
TAKEOVER-T6B：已完成——Tools 维护操作和 backlog 安全收口
TAKEOVER-T7：等待维护窗口——当前 100+ 混合任务存在，不执行真实小批量整理
TAKEOVER-T8A：已完成——迁移 manifest、递归 part/symlink、四表同步、删除确认和沙盒验收
TAKEOVER-T8B：已完成——资源库完整快照、原子索引替换、陈旧清理、重复 RJ 主路径和递归音轨验证
```

## 8.1 当前验证结果

```text
隔离虚拟环境：Flet 0.27.6 legacy API import PASS
python -m pytest：183/183 passed
全项目 compileall：PASS
pip check：PASS
活跃状态文件保护：发现 history.db 时 pytest 固定 exit 2
SQLite 在线备份：WAL 并发写入期间 snapshot integrity_check=ok
快照 manifest：size + SHA-256 验证通过
混合下载状态报告：completed/failed/paused/queued/downloading 统计通过
本地 ASMR 兼容下载：1 MiB final size + SHA-256 PASS
真实 aiohttp 200/206/416：PASS
过期 metadata cache 恢复与嵌套音轨 UI fallback：PASS
真实 ASMR.one：当前容器 DNS 阻塞，待 Windows sandbox
Flet 视觉点击：当前容器浏览器策略/libmpv 阻塞，待 Windows sandbox
external intake 复制资源库验收：11/11 checks PASS；迁移 T8A 沙盒验收：10/10 checks PASS
资源库 T8B 快照重建验收：10/10 checks PASS
GitHub Actions：Linux 3.10 + Windows 3.12 workflow 已生成，尚待最终推送后真实运行
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
当前优先级不是播放器。T8A 迁移代码级收口已完成；T7 在 100+ 活跃/可恢复任务清空前保持冻结。下一项处理资源库 rebuild 快照写入、旧索引清理和剩余 UI 稳定性，同时等待 Windows 隔离下载/UI 证据。
```
