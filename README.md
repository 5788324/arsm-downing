# ARSM Suite

面向个人本地使用的 Windows ASMR/RJ 下载、断点续传与资源库管理工具。

```text
Python + Flet 0.27.6 + SQLite + asyncio + aiohttp
```

## 当前状态

> 2026-08-23 最新功能分支：`codex/asmr-browser-extension`；功能代码检查点为 `0fe8afcb0a45f4f554f923b62f68581c7e3ad723`，其后仅追加交接文档提交。以远端分支最新 HEAD 为准。

- v1.0.1 修复分支：`fix/v1.0.1-download-freeze-ui`，PR #21（Draft，Fixes #19 #20）。
- 已修复 Issue #20（UI 冻结 / 签名 URL 重试风暴 / 虚假总进度）与 Issue #19（下载页布局闪烁）。
- PR 四轮代码审查阻塞已修复：并发签名刷新单飞、refresh/transport budget 分离、磁盘核验移出 UI 线程且启动只跑一次、真实进度贯通 read model、UI 单调度器、文件树详情与同名文件实时更新、实时总进度统一（全作品基线）、registered/completed 磁盘不完整降级、partial 走 resume/reconcile、Working 核验后分页、交付文档。
- 全量回归：`377 passed, 3 skipped`；CI（head `facf351`）：Windows **380 passed**、Ubuntu **379 passed, 1 skipped**；release_check `ready: true`；PyInstaller `ARSM-Suite-1.0.1-windows-x64.zip`。
- 当前为 **NO-GO**：真实 GUI/DPI/托盘、9 任务约 2700 文件压力与 300 个集中 400 场景验收通过前不转 Ready、不发布。
- 浏览器扩展已在独立分支实现：支持 `asmr.one` / `www.asmr.one` 入库标签、下载按钮、本机安全桥接、设置页安装管理、地址/令牌复制及断线恢复；全量回归 `410 passed, 3 skipped`。Edge 列表页连接已实机通过，Chrome 与详情页入队矩阵仍待补验。

## T10 已完成

- `DownloadService` + 不可变 read models；
- 10/50/100/200 个任务均固定两次 SQLite `SELECT`；
- 下载队列分页、状态筛选和默认隐藏完成项；
- 批量粘贴主入口：应用内多行输入，不依赖 Windows 原生 FilePicker；
- 批量 RJ 预览：无效、输入重复、活动中、队列已有、资源库已有、历史完成、待复核；
- 支持 RJ 号、纯数字和 ASMR.one 作品链接；
- 独立 `MetadataScheduler`，默认并发 2，与音频下载槽分离；
- 页面 active/inactive 生命周期；
- 显式状态迁移策略，不批量改写旧数据库；
- RC2 全局网速、作品网速、全部暂停/继续和完成项即时移除保持不变。

本地隔离验证：

```text
compileall：PASS
批量粘贴修复本地测试桩：238/238 PASS
Windows 修复前基线：231 passed，3 skipped
200 个任务队列快照：2 次 SELECT
100 个 metadata 作业：峰值并发 2
```

当前容器没有项目锁定的真实 Flet，因此 UI 自动测试使用不进入交付包的临时接口桩。真实 Flet 0.27.6、Windows 构建和桌面交互由 Codex 完成。

## 核心能力

- ASMR.one 元数据、封面和递归文件列表；
- HTTP 200/206/416 严格断点续传；
- `.part` 暂停、关闭、重启与恢复；
- 作品/文件并发、代理与镜像切换；
- SQLite 下载状态和资源库；
- 资源库搜索、分页、异常诊断和原子索引重建；
- External Intake、迁移、Journal、回滚和沙盒验收；
- Tools、缓存、队列预览、VACUUM 安全门和 backlog；
- PyInstaller Windows one-folder 构建。

## 架构约束

```text
history.db / SQLite = 唯一业务真源
LibraryVault = 正式数据库访问入口
UI 不自行 sqlite3.connect()
queue.json 不作为历史状态真源
测试不访问正式 E:\arsm 或正式 history.db
普通优化不修改数据库 schema、旧 local_path 或旧 .part
```

## 启动与测试

```powershell
python -m pip install -r requirements.txt
Copy-Item config.example.json config.json
python main.py

python -m pip install -r requirements-dev.txt
python -m compileall -q core ui tools tests scripts main.py
python -m pytest -q
```

## Windows 构建

```powershell
.\scripts\build_windows.ps1
```

## 当前冻结

- External Intake 正式 Execute；
- 正式资源库迁移、移动、隔离和删除；
- 正式数据库 VACUUM；
- 正式 backlog execute；
- T7 真实目录整理；
- 对现有 100+ 混合任务批量改状态或路径。

## 文档入口

- [`CURRENT_STATE.md`](CURRENT_STATE.md)
- [`NEXT_TASK_ROADMAP.md`](NEXT_TASK_ROADMAP.md)
- [`PROJECT_ROADMAP.md`](PROJECT_ROADMAP.md)
- [`WORKLOG.md`](WORKLOG.md)
- [`DECISIONS.md`](DECISIONS.md)
- [`HANDOFF.md`](HANDOFF.md)
- [`AI_WORKFLOW.md`](AI_WORKFLOW.md)
- [`docs/TAKEOVER_T10_QUEUE_SERVICE.md`](docs/TAKEOVER_T10_QUEUE_SERVICE.md)
- [`docs/T10_BATCH_PASTE_FIX.md`](docs/T10_BATCH_PASTE_FIX.md)
- [`docs/BROWSER_EXTENSION_TASKS.md`](docs/BROWSER_EXTENSION_TASKS.md) / [`docs/BROWSER_EXTENSION_ACCEPTANCE.md`](docs/BROWSER_EXTENSION_ACCEPTANCE.md)
- [`docs/CODEX_WINDOWS_ACCEPTANCE_RC1_RESULT.md`](docs/CODEX_WINDOWS_ACCEPTANCE_RC1_RESULT.md)

## License

Based on `takoyune/asmr.one-downloader`, MIT License. See [`LICENSE`](LICENSE).


## 2026-08-01 RC2 T10 隔离 Windows 验收更新

- 真实 Flet 0.27.6；compileall 和 git diff --check 均通过；pytest 为 230 passed、3 skipped（Windows 符号链接不可用）。
- RC2 ZIP：ARSM-Suite-0.9.0-rc.2-windows-x64.zip，57,247,433 bytes，195 项，SHA-256 a8961e730111519b49200ff7c82f06930fd81d0d30e6aaba19e829c37416fdb3。
- 七种队列筛选、分页回退、四页导航、metadata_concurrency 重启持久化、三轮正常关闭均已在隔离目录通过。
- 本机 127.0.0.1 限速 HTTP 流已完成真实下载、暂停、非空 .part 保留、Range 206 续传、最终文件与完成项移除验证。
- 原生 FilePicker 已从批量输入主链路移除，改为应用内“批量粘贴”多行对话框；代码与回归测试已完成，等待 Codex 在真实 Flet 0.27.6 最终二进制中验证取消零副作用和确认仅加入 ready 项。结论仍为条件 GO；验证通过前不提交、不推送、不建 PR、不发布。
- 正式 history.db、config.json、queue.json、E:\arsm、现有任务和正式 .part 均未访问或修改。


## 2026-08-01 T10 批量粘贴 Fix2 真实 Windows 复测

- 真实 Flet `0.27.6`：输入对话框与批量预览均已在隔离 Windows EXE 显示；原生 FilePicker 不再参与主链路。
- 修复了两项真实 Flet/GUI 缺陷：对话框改用 `page.open(dialog)` / `page.close(dialog)`，并且不再把下载页展示缓存误判为“当前活动”。
- 自动验证：对话框定向 `18 passed`；完整回归 `236 passed, 3 skipped`。3 项 skipped 均为 Windows 环境无法创建符号链接。
- Fix2 构建：`ARSM-Suite-0.9.0-rc.2-windows-x64.zip`，57,249,902 bytes，195 entries，SHA-256 `e5eb73c033a7cac62b053f52846eb92b71d5214b73f348b3f4f4ff2d6ccdcbc7`，包含 `ARSM-Suite.exe`。
- 输入取消零副作用：`works=0`、`downloads=0`、活动任务 `0`、下载文件 `0` 均保持不变。
- 预览取消零副作用：隔离夹具的 `works=2`、`downloads=1`、`library_items=1`、活动 `1`、下载文件 `0` 均保持不变。
- 混合输入已现场显示完整分类：ready 2、invalid 1、duplicate 1、active 0、queue 1、library 1、completed 1、review 1；不存在静默丢项。
- 确认“添加 2 项”只为 `RJ00000001` 和 `RJ00000008` 取得 metadata 槽位；其他分类没有启动。外网 metadata 在 150 秒内未返回且未落库，按 T12 `BLOCKED_BY_NETWORK/AUTH` 记录，不视为下载成功。
- 正式 `history.db`、`config.json`、`queue.json`、`E:\arsm`、正式任务和 `.part`：零接触。

当前结论：批量粘贴 GUI 与分类逻辑 PASS；整体 RC2 保持“条件 GO”，等待 T12 隔离真实网络/认证验收后再决定 Git 放行与发布。
## 2026-08-01 T11/T12 隔离真实网络与长期运行收口

- 新增 `scripts/t11_t12_live_acceptance.py`：只允许新 sandbox，真实复用 `Orchestrator`；audio 最小优先、最多 4 文件且总量不超过 64MiB。
- `RJ01276295` 真实音频验收通过：4/4 完成，总计 `30,285,707` bytes；暂停时 `.part=54,694` bytes 稳定，服务重建后收到 HTTP `206` Range 续传，最终活动任务为 0。
- 连续运行 `2,741.38` 秒，27 个一分钟 SQLite 快照稳定；正常 shutdown，无本验收 ARSM/Python 遗留进程。
- 详细证据：`docs/T11_T12_REAL_NETWORK_LONG_RUN.md` 及隔离 sandbox 的 JSON、日志和文件哈希。可见四页长时往返未在本轮重做，继续沿用 T10 Windows 证据；Defender、长路径、文件占用均未触发。
- 当前为 **条件 GO**：不得据此发布、提交或推送；先完成最终自动回归与人工代码/CI 复核。
## 最终自动回归（2026-08-01）

- 在新建的无运行数据源码副本中，固定可写 TEMP 后执行：`236 passed, 3 skipped in 95.43s`。
- 3 个 skipped 均为 Windows 环境无法创建 symbolic link；`compileall` 与真实 Flet 导入通过。
- 当前工作树旁的 pytest 保护门拒绝执行，是因为隔离验收运行已生成本地 `history.db/config.json`；该拒绝是预期安全机制，不是测试失败。
- 新增验收脚本不被冻结应用导入，未改变下载器生产模块或 Windows one-folder 包内容，因此本轮不重复构建 ZIP；既有 RC2 Fix2 构建仍仅作为上一轮二进制证据，未因此放行发布。
## 2026-08-02 RC2 最终关闭与可见 GUI 验收

- 修复 Flet 0.27.6 窗口生命周期兼容性：关闭事件、阻止默认关闭、销毁窗口均改用 `page.window` API。旧 API 会让原生窗口先消失而保留 Python/下载器进程。
- 无运行数据的隔离源码副本已完成真实 Flet 回归：`237 passed, 3 skipped`；3 个 skipped 均为 Windows 环境不支持符号链接。`compileall`、Flet import 与 `git diff --check` 通过。
- 最终 one-folder：`ARSM-Suite-0.9.0-rc.2-windows-x64.zip`，57,251,928 bytes、195 entries，SHA-256 `37bece06a014631c8756a41de237a6d77db7de7f0f50949257550bdb65ee8e08`；SHA 文件一致，ZIP 内含 `ARSM-Suite.exe`，EXE File/ProductVersion 均为 `0.9.0-rc.2`。
- 最终 EXE 的下载中心、资源库、系统工具、设置四页已可见往返并保存隔离截图；标题栏关闭连续 3 次均记录完整 shutdown，ARSM-Suite 与 Flet 子进程均为零残留。
- 正式 `history.db`、`config.json`、`queue.json`、`E:\arsm`、正式任务与 `.part`：零接触。本地验收通过，下一门槛仅为 Git 提交、PR 与远端 CI；尚未创建 Release。
### 资源库体验

资源库以分页海报墙展示。点击专辑可在右侧查看只读元数据和最多 200 项文件预览；支持分类、排序、复制 RJ/路径及打开该专辑目录，不会移动正式资源库文件。

### 系统托盘

Windows 下点击标题栏关闭会隐藏到系统托盘。右键托盘图标可打开窗口、暂停/继续全部任务或彻底退出；若托盘后端不可用，应用会安全退出而不留下后台进程。

## 2026-08-02 RC2 正式预发布收口

- PR #10 已合并：`main@8c4215ac5d5a80c0d62c683adcc40cd7f04e216d`；T13 资源库详情和 T14 托盘生命周期已进入主线。
- 正式标签：`v0.9.0-rc.2`，解引用提交精确为上述 main SHA。
- GitHub `windows-release-candidate` 构建通过：`https://github.com/5788324/arsm-downing/actions/runs/30712870981`。
- 正式 Artifact/Pre-release ZIP：`ARSM-Suite-0.9.0-rc.2-windows-x64.zip`，65,206,571 bytes、212 项、SHA-256 `5a6179098faf4e44ca410e87b518c71a418ee7ae09227e236af05e7c51494061`；校验文件一致并含 `ARSM-Suite.exe`。
- Release：`https://github.com/5788324/arsm-downing/releases/tag/v0.9.0-rc.2`（Pre-release）。
- 正式 `E:\arsm`、正式数据库、队列、下载任务与 `.part`：全流程零接触。
## 2026-08-02 T15 真实网络与认证验收

- `RJ01276295` 在全新 `C:\tmp` sandbox 通过真实 metadata/封面代理、音频直连、暂停稳定、HTTP 206 续传和两文件完整校验；详情见 `docs/T15_NETWORK_AUTH_ACCEPTANCE.md`。
- 修复 metadata 失败原因被降级为 `empty response`：401 和断网现在会把具体 HTTP/连接错误传到下载器状态；受控真实 HTTP 401、断网和恢复均已验证，失败时 SQLite 零新增。
- 最终自动回归：`245 passed, 3 skipped`；3 项 skipped 是当前 Windows 无法创建 symbolic link。
- 正式 `E:\arsm`、history/config/queue、正式任务与 `.part` 全程零接触；本轮未创建标签或发布。

## PR1 维护安全候选（2026-08-02）

已取消任务是可显式恢复的终态：它不阻止数据库 VACUUM 或队列清理预览，但会保护 metadata cache，避免重试前丢失元数据。该候选已在隔离 Windows 环境通过 294 项自动测试、PyInstaller 与基础 GUI/托盘退出验收；仍需在用户实际高 DPI 缩放下做视觉复核，当前不是正式 Release。

## v1.0.1 P0 修复（2026-08-05/06）

- 同一分支 `fix/v1.0.1-download-freeze-ui`、同一 PR #21（Draft）内完成 Issue #20 与 #19。
- 关键修复：bounded worker pool；签名 URL 单飞刷新 + `ensure_refreshed_once`；refresh/transport budget 分离（二次签名失效 fail-closed，`retry_count=1` 也尝试新 URL，日志脱敏）；磁盘核验移出 UI 线程（`run_blocking` + generation token）；真实进度使用 `verified_bytes`、`registered` 非终态、成功保持 `completed`、混合大小分母修复；UI 单调度器守卫 + 数量/时间双预算；下载页稳定列表 + 右侧文件树详情（相对路径 key、失败原因、`.part` 状态、每状态唯一按钮）。
- 新增回归测试覆盖并发单飞刷新、二次 403、日志脱敏、混合进度、非阻塞刷新、单调度器真实 asyncio 调度、文件树与按钮、同名不同目录文件的 track_id 实时更新、registered/completed 磁盘不完整降级、实时总进度统一，以及恢复任务全作品进度、mixed 完整性、partial resume 与 Working 核验后分页。
- 全量回归：`377 passed, 3 skipped`。正式 E:\arsm 与既有运行数据零接触。
