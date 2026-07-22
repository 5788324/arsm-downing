# ARSM Suite 当前状态

> 更新时间：2026-07-22  
> 当前发布：`v0.9.0-rc.1`  
> 默认分支：`main`  
> main 提交：`9f292e7947804f2e4d53290039501f79c6d1805d`  
> 当前开发分支：`chatgpt/optimize-o1-20260722`

## 1. 阶段结论

主要功能开发已经收口，项目已从“接手与发布候选开发”进入“性能、交互和长期运行体验优化”。

```text
主要开发：完成
0.9.0-rc.1 发布：完成
Git 仓库清理：完成
Windows 最终现场验收：Codex 进行中
优化阶段 O1：已开始
高风险资源库维护：继续冻结
```

## 2. 已完成基线

- 下载核心：HTTP 200/206/416、Range、`.part`、暂停、恢复、重连、失败和镜像切换；
- 元数据缓存：TTL、离线恢复和三通道代理；
- SQLite：`works`、`downloads`、`library_items`、`library_index`；
- 资源库：搜索、过滤、分页、异常诊断、快照重建和陈旧索引清理；
- External Intake：只读计划、逐文件映射、四表事务、staging、Journal、回滚和恢复；
- 迁移：manifest、递归 `.part`/symlink 检查、四表同步和失败回滚；
- Tools：缓存、队列预览、VACUUM 安全门、backlog 和诊断；
- 发布：Windows PyInstaller one-folder、ZIP、SHA-256 和 Pre-release；
- 自动测试：Ubuntu / Windows portable CI，205/205 PASS。

正式 Release：

```text
https://github.com/5788324/arsm-downing/releases/tag/v0.9.0-rc.1
SHA-256:
fe00bb9d47a6b16949573b57a2c483f1121e3a8b3fec0777d101ae82e15747c2
```

## 3. 仓库清理状态

用户与 Codex 已完成清理：

```text
本地仓库：G:\Antigravity\arsm.one\arsm-downing
本地分支：仅 main
远端分支：仅 main
工作区：clean
保留标签：v0.9.0-rc.1
保留 Release：ARSM Suite 0.9.0-rc.1
```

已删除旧接手、UI 自测和废弃 v2 分支；未修改 `main`，未接触正式数据库或下载任务。

本轮重新从最新 `main` 创建：

```text
chatgpt/optimize-o1-20260722
```

## 4. Codex 当前验收

Codex 使用正式 Release 在独立 Windows 目录进行：

- ZIP 和 SHA-256 复核；
- Flet Desktop 肉眼布局；
- 三次启动和关闭；
- 设置持久化；
- 真实 ASMR.one 小样本；
- 暂停、保留 `.part`、重启和恢复；
- 进程残留、文件占用和日志检查；
- 正式环境零接触确认。

验收文档：

[`docs/CODEX_WINDOWS_ACCEPTANCE_RC1.md`](docs/CODEX_WINDOWS_ACCEPTANCE_RC1.md)

Codex 发现阻塞问题时，先登记 RC 修复；普通 UI 和性能建议进入优化路线。

## 5. 当前 O1 优化范围

本轮只做低风险只读模型和队列基础，不修改下载文件和旧任务路径：

- 新增 `DownloadTaskSnapshot`、`DownloadQueueSummary` 和 `DownloadQueuePage`；
- 使用一次 SQL 聚合生成任务级状态，避免每个卡片分别查询；
- 支持 `working / active / queued / paused / failed / completed / all` 过滤；
- 支持有上限的分页；
- 新增纯函数批量 RJ 预览：规范化、输入去重、无效项、活动任务和已知作品分类；
- 为后续 UI 接入、独立元数据并发池和检查点落库提供基础。

## 6. 必须保持的边界

```text
history.db / SQLite = 唯一业务真源
LibraryVault = 正式数据库访问入口
UI 不直接 sqlite3.connect()
Read Model 只能读取，不成为第二真源
新优化不得自动迁移数据库 schema
新优化不得修改旧任务 local_path
新优化不得删除或重置 .part
```

## 7. 继续冻结

```text
python tools/external_intake.py --execute --confirm-bulk
External Intake 正式执行入口
正式资源库批量迁移和隔离
正式数据库 VACUUM
正式 backlog execute
T7 真实目录整理
对现有 100+ 任务的批量状态或路径改写
```

## 8. 当前下一步

1. 完成 O1 Read Model 和批量预览基础；
2. portable tests 与 Windows CI 全绿；
3. 将 DownloadView 接入分页、过滤和一次聚合查询；
4. 增加独立元数据并发池；
5. 审计并降低实时进度的 SQLite 写入频率；
6. Codex 对 O1 Windows UI 和暂停/恢复进行实机验收；
7. 发布 `0.9.0-rc.2`。
