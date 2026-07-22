# ARSM Suite 当前状态

> 更新时间：2026-07-22
> 当前发布：`v0.9.0-rc.1`
> 默认分支：`main`
> main 提交：`9f292e7947804f2e4d53290039501f79c6d1805d`
> 当前开发分支：`chatgpt/optimize-o1-20260722`
> 当前 PR：`#6 feat: start O1 download queue optimization`

## 1. 阶段结论

主要功能开发和 `0.9.0-rc.1` 发布已经完成。项目当前处于 `0.9.0-rc.2` 性能与交互优化阶段。

```text
主要开发：完成
0.9.0-rc.1 发布：完成
Git 仓库清理：完成
RC1 Windows 最终现场验收：Codex 进行中
O1 下载队列与调度优化：代码侧完成，PR CI 待验证
高风险资源库维护：继续冻结
```

## 2. 正式发布基线

```text
Release：https://github.com/5788324/arsm-downing/releases/tag/v0.9.0-rc.1
标签：v0.9.0-rc.1
main：9f292e7947804f2e4d53290039501f79c6d1805d
Windows ZIP SHA-256：
fe00bb9d47a6b16949573b57a2c483f1121e3a8b3fec0777d101ae82e15747c2
```

已完成能力：

- HTTP 200/206/416、Range、`.part`、暂停、恢复、重连和失败重试；
- 元数据缓存、离线恢复、镜像切换和三通道代理；
- SQLite 下载状态和资源库；
- 资源库搜索、过滤、分页、异常诊断和快照重建；
- External Intake 计划、四表事务、staging、Journal、回滚和恢复；
- 迁移 manifest、四表同步、失败回滚和 post-verify；
- Tools、缓存、队列预览、VACUUM 安全门和 backlog；
- PyInstaller Windows one-folder、ZIP、SHA-256 和 Pre-release；
- `0.9.0-rc.1` Ubuntu / Windows portable CI：205/205 PASS。

## 3. 仓库状态

清理完成后，本地和 GitHub 远端只保留 `main`；随后从最新 `main` 创建当前唯一任务分支：

```text
chatgpt/optimize-o1-20260722
```

本地唯一正式仓库：

```text
G:\Antigravity\arsm.one\arsm-downing
```

旧 v2、验收、构建、ZIP、缓存、日志、虚拟环境和旧 Git 仓库均已清理。`v0.9.0-rc.1` 标签和 Release 保留。

## 4. Codex 当前验收

Codex 使用正式 Release，在独立 Windows 目录检查：

- ZIP、标签和 SHA-256；
- 三次启动和关闭；
- Flet Desktop 布局和五个主要页面；
- 设置持久化；
- 真实 ASMR.one 小样本；
- `.part`、暂停、关闭、重启和恢复；
- 进程残留、文件锁和正式环境零接触。

验收文档：

[`docs/CODEX_WINDOWS_ACCEPTANCE_RC1.md`](docs/CODEX_WINDOWS_ACCEPTANCE_RC1.md)

RC1 实机验收与 O1 开发相互隔离。Codex发现阻塞问题时只提交证据，由 ChatGPT 单独判断是否建立 RC 修复任务。

## 5. O1 本轮已完成

### 下载队列 Read Model

- `DownloadTaskSnapshot`、`DownloadQueueSummary`、`DownloadQueuePage`；
- `works + downloads` 有界聚合查询；
- 下载记录缺少 `works` 行时仍可显示；
- 终态作品不会被历史 paused/failed 行重新显示为活动任务；
- `registered` 文件纳入已完成统计；
- 独占状态：活动、等待、暂停、失败、完成；
- 过滤：`working / active / queued / paused / failed / completed / all`；
- 分页默认 24，单页最多 200，越界页自动收敛；
- 默认隐藏已完成任务。

### DownloadView 接入

- 队列页使用 Read Model，不再逐卡片查询 works/downloads；
- 状态筛选、刷新、上一页、下一页和页码；
- 队列摘要来自统一聚合模型；
- 卡片标题、社团、路径、封面和总进度来自 Snapshot；
- 屏外分页任务不反复重建控件；
- 后台刷新失败会恢复按钮并显示错误；
- 实时速度、ETA、当前文件和当前字节保留在内存。

### 批量 RJ 预览

- 严格识别 6~8 位 RJ；
- 支持空格、换行、中英文逗号和分号；
- 输入内去重；
- 分类无效项、活动任务和已知作品；
- 批量输入先显示预览，确认后才入队；
- 预览阶段不写 SQLite、不创建目录、不启动下载。

### 独立元数据并发

- 新增 `metadata_concurrency`，默认 2，范围 1~8；
- 元数据请求使用独立 Semaphore；
- 不占用音频文件并发槽；
- 设置页和示例配置已接入；
- 并发日志显示 work / metadata / file 三类配置。

### SQLite 写入频率审计

- 下载分块进度只更新内存事件；
- 不按每个 chunk 写 SQLite；
- 当前文件开始写一次 `downloading`；
- 暂停、失败、完成和退出仍保存检查点；
- `.part` 继续作为恢复字节数的最终依据。

## 6. 测试状态

本地隔离验证：

```text
python -m compileall -q core ui tests
PASS

python -m pytest -q
220 passed
```

本地容器未安装项目锁定的 Flet，因此 UI 语义测试使用仅存在于本地测试路径的轻量 Flet stub；该 stub 不进入仓库。真正的 Flet 0.27.6、Ubuntu Python 3.10 和 Windows Python 3.12 由 PR #6 CI 验证。

## 7. 必须保持的架构边界

```text
history.db / SQLite = 唯一业务真源
LibraryVault = 正式数据库访问入口
UI 不直接 sqlite3.connect()
Read Model 只读，不成为第二真源
O1 不迁移数据库 schema
O1 不修改旧任务 local_path
O1 不删除或重置旧 .part
```

## 8. 继续冻结

```text
External Intake 正式 Execute
正式资源库批量迁移和隔离
正式数据库 VACUUM
正式 backlog execute
T7 真实目录整理
对现有 100+ 任务的批量状态或路径改写
```

## 9. 当前下一步

1. 将本轮代码和文档作为一个原子提交推送到 PR #6；
2. 核对 Ubuntu / Windows CI 和真实 Flet 0.27.6；
3. CI 失败时最多进行一次修复推送；
4. Codex完成 RC1 实机验收；
5. 生成 O1 Windows 验收 Artifact 和专用验收清单；
6. O1 验收通过后将 PR 转 Ready、合并并发布 `0.9.0-rc.2`；
7. 下一独立 PR 进入 O2 Windows 系统托盘。
