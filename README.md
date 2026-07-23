# arsm-downing / ARSM Suite

面向个人本地使用的 Windows ASMR/RJ 下载、资源库与维护工具。

当前稳定主线继续保持为单体桌面应用：

```text
Python + Flet + SQLite + asyncio + aiohttp
```

核心模块：

- ASMR.one 下载、暂停、恢复、失败重试与严格断点续传；
- SQLite 下载状态与本地资源库；
- 资源库搜索、异常识别、分页和快照式索引重建；
- 目录迁移与 External Intake 的 dry-run、事务、Journal、回滚和恢复；
- 队列、缓存、VACUUM、backlog 与诊断工具；
- Windows PyInstaller one-folder 便携构建。

## 当前状态

当前版本：`0.9.0-rc.1`。

PR #1 已于 2026-07-21 合并到 `main`：

```text
main merge commit：9f292e7947804f2e4d53290039501f79c6d1805d
portable tests：205/205 PASS
Windows release workflow：PASS
Windows artifact：PASS
自动 Windows 启动验收：PASS_WITH_NOTES
```

已验证的发布产物：

```text
ARSM-Suite-0.9.0-rc.1-windows-x64.zip
SHA-256：b60125d5fddebd056d292a8dccb485d512d52eb65865db9534e1a874de20f2cb
```

`PASS_WITH_NOTES` 表示代码、CI、Windows 构建和隔离启动已经通过，但以下现场证据仍未完成：

- 用户桌面上的 Flet Desktop 视觉与鼠标交互；
- 真实 ASMR.one 网络小样本；
- Windows Defender、长路径和第三方文件占用观察。

这些缺口不推翻已完成的 RC 合并，但在稳定版前仍需补齐。

## 当前开发阶段

项目已从“接手与发布候选收口”进入：

```text
Post-RC 稳定化与大队列优化
```

下一阶段优先吸收已放弃的 ARSM Library v2 中有价值的设计思想，但不合并其代码、数据库或下载引擎：

1. 下载只读模型和 Service 门面；
2. 100+ 任务的批量队列快照，消除 N+1 查询；
3. 元数据准备队列与音频下载队列分离；
4. 批量 RJ 预览、查重、确认后统一入队；
5. 显式状态迁移规则；
6. 页面 active/inactive 生命周期，隐藏页面停止无意义刷新；
7. 后续资源库分类、排序和详情侧栏；
8. 托盘模式留到更后阶段。

详细任务见 [`NEXT_TASK_ROADMAP.md`](NEXT_TASK_ROADMAP.md) 和 [`docs/POST_RC_OPTIMIZATION_BACKLOG.md`](docs/POST_RC_OPTIMIZATION_BACKLOG.md)。

## 核心架构约束

```text
history.db / SQLite = 业务唯一真源
LibraryVault = 正式数据库访问入口
UI 不直接 sqlite3.connect()
queue.json 不作为历史下载状态真源
扫描 JSON / manifest 只作为报告、缓存或审计证据
文件移动、隔离和删除必须先 dry-run，并具备可核验恢复路径
```

当前主线不接受以下变更：

- 用新的 `library.db` 替换现有 `history.db`；
- 导入已放弃 v2 的 `download_tasks/download_files` 数据模型；
- 用较弱的续传实现替换当前 200/206/416 逻辑；
- 在 UI 中新增独立 `LibraryVault()` 或裸 SQLite 连接；
- 在现有 100+ 混合状态任务运行期间执行正式迁移、VACUUM 或批量状态写入。

## 启动

```powershell
python -m pip install -r requirements.txt
Copy-Item config.example.json config.json
python main.py
```

`config.json` 属于本机配置，不提交到 Git。

## 测试

```powershell
python -m pip install -r requirements-dev.txt
python -m compileall -q core ui tools tests scripts main.py
python -m pytest
```

默认自动测试只使用临时目录、临时 SQLite 和模拟网络，不应连接正式 `history.db` 或读取真实 `E:\arsm`。

## Windows 构建

```powershell
.\scripts\build_windows.ps1
```

详见 [`docs/BUILD_AND_RELEASE.md`](docs/BUILD_AND_RELEASE.md)。

## 当前冻结操作

```text
python tools/external_intake.py --execute --confirm-bulk
External Intake 正式 execute
正式资源库批量迁移、移动、隔离或删除
正式 history.db VACUUM
正式 backlog execute
T7 真实目录整理
覆盖当前仍在下载的正式程序目录
```

开放这些操作前必须等待明确维护窗口，并使用在线只读 SQLite snapshot、manifest 和小批量验收。

## 文档入口

- [`CURRENT_STATE.md`](CURRENT_STATE.md)：当前事实基线和剩余风险
- [`NEXT_TASK_ROADMAP.md`](NEXT_TASK_ROADMAP.md)：当前可执行任务顺序
- [`PROJECT_ROADMAP.md`](PROJECT_ROADMAP.md)：中长期产品路线
- [`WORKLOG.md`](WORKLOG.md)：当前阶段工作日志
- [`DECISIONS.md`](DECISIONS.md)：关键架构与范围决策
- [`HANDOFF.md`](HANDOFF.md)：下一位 AI/Windows 验收者交接说明
- [`docs/POST_RC_OPTIMIZATION_BACKLOG.md`](docs/POST_RC_OPTIMIZATION_BACKLOG.md)：v2 可吸收设计与实施边界
- [`docs/TESTING_AND_CI.md`](docs/TESTING_AND_CI.md)：测试和活跃数据保护
- [`docs/WINDOWS_READ_ONLY_ACCEPTANCE.md`](docs/WINDOWS_READ_ONLY_ACCEPTANCE.md)：Windows 只读现场验收
- [`docs/archive/WORKLOG_20260627_20260721.md`](docs/archive/WORKLOG_20260627_20260721.md)：接手前至 RC 合并的完整历史日志

## 协作流程

```text
一个任务 = 一个分支 + 一个 PR
本地批量修改后一次正式提交
真实 CI 失败最多一次修复推送
main 只接收通过测试与审查的 PR
文档与代码在同一任务中同步更新
```

用户不负责日常 Git、测试、构建或发布。ChatGPT 负责可在当前环境完成的开发与审查；Windows/Flet/真实网络证据只在确实需要时交给本机执行者。

## License

Based on `takoyune/asmr.one-downloader` and licensed under the MIT License. See [`LICENSE`](LICENSE).
