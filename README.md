# ARSM Suite

面向个人本地使用的 Windows ASMR/RJ 下载与媒体库桌面工具。

## 当前状态

```text
当前发布：v0.9.0-rc.1
main：9f292e7947804f2e4d53290039501f79c6d1805d
开发阶段：主要功能开发已收口
当前阶段：0.9.0-rc.2 性能与交互优化
优化总任务：GitHub Issue #5
```

`0.9.0-rc.1` 已完成：

- ASMR.one 元数据、文件列表和下载；
- HTTP 200/206/416、`.part`、暂停、恢复和失败重试；
- SQLite 下载状态与资源库；
- 资源库搜索、过滤、分页、异常诊断和快照重建；
- External Intake 计划、事务、Journal、回滚和沙盒验收；
- 迁移 manifest、四表同步、失败回滚和 post-verify；
- Tools、缓存、队列预览、VACUUM 安全门和 backlog；
- PyInstaller Windows one-folder 构建；
- Ubuntu / Windows CI，portable tests 205/205 PASS；
- 正式 Windows Pre-release。

正式 Release：

https://github.com/5788324/arsm-downing/releases/tag/v0.9.0-rc.1

## 当前优化方向

第一阶段 O1 聚焦下载队列和调度，不迁移数据库、不修改旧任务路径：

- 下载队列统一只读 Read Model；
- 一次聚合查询任务状态，消除队列卡片 N+1 查询；
- 下载队列分页和状态过滤；
- 默认隐藏已完成任务；
- 批量 RJ 输入先预览、去重、查重，再确认入队；
- 后续增加独立元数据并发池；
- 审计实时进度的 SQLite 落库频率。

详细计划见：

- [`CURRENT_STATE.md`](CURRENT_STATE.md)
- [`NEXT_TASK_ROADMAP.md`](NEXT_TASK_ROADMAP.md)
- [`PROJECT_ROADMAP.md`](PROJECT_ROADMAP.md)
- [Issue #5：0.9.0-rc.2 优化路线图](https://github.com/5788324/arsm-downing/issues/5)

## 核心架构约束

```text
history.db / SQLite = 唯一业务真源
LibraryVault = 正式数据库访问入口
UI 不直接 sqlite3.connect()
扫描 JSON / manifest 不作为 UI 主数据源
文件移动、隔离、删除必须先 dry-run，并保留可验证回滚信息
现有 100+ 任务的路径和状态不得由优化任务批量改写
```

## 技术栈

```text
Python 3.10+
Flet 0.27.6
SQLite
asyncio
aiohttp / aiofiles
mutagen
PyInstaller
```

主入口：

```powershell
python main.py
```

## 安装与运行

```powershell
git clone https://github.com/5788324/arsm-downing.git
cd arsm-downing

py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item config.example.json config.json
python main.py
```

`config.json` 是本机配置，不应提交到 Git。

## 测试

```powershell
python -m pip install -r requirements-dev.txt
python -m compileall -q core ui tools tests scripts main.py
python -m pytest
```

默认测试使用临时目录、临时 SQLite 和模拟网络。禁止在正式程序目录或活跃下载环境中运行测试。

## Windows 构建

```powershell
.\scripts\build_windows.ps1
```

发布和构建说明见 [`docs/BUILD_AND_RELEASE.md`](docs/BUILD_AND_RELEASE.md)。

## Codex 实机验收

Codex 使用正式 Release，在独立目录完成桌面 UI、真实 ASMR.one 小样本、暂停/恢复、设置持久化和进程退出验收：

[`docs/CODEX_WINDOWS_ACCEPTANCE_RC1.md`](docs/CODEX_WINDOWS_ACCEPTANCE_RC1.md)

## 继续冻结

```text
External Intake 正式 Execute
正式资源库批量迁移
正式数据库 VACUUM
正式 backlog execute
T7 真实目录整理
对现有 100+ 任务的批量状态或路径修改
```

这些操作只能在明确维护窗口中单独开放。

## 项目结构

```text
main.py
core/                       下载、数据库、资源库、迁移与安全事务
ui/                         Flet 应用与页面
tools/                      External Intake、backlog 等工具
tests/                      默认 portable 自动测试
scripts/                    构建、快照、诊断和验收脚本
docs/                       规范、验收、路线和交接文档
CURRENT_STATE.md            当前事实基线
NEXT_TASK_ROADMAP.md        当前可执行任务
PROJECT_ROADMAP.md          中长期路线
HANDOFF.md                  当前交接
AI_WORKFLOW.md              AI、Git 和验收流程
WORKLOG.md                  历史工作日志
```

## License

Based on `takoyune/asmr.one-downloader` and licensed under the MIT License. See [`LICENSE`](LICENSE).
