# ARSM Suite 关键决策

## D-20260723：保留现有主线

`history.db + LibraryVault + 当前下载核心` 继续作为唯一正式架构。放弃 ARSM Library v2，不导入其数据库、下载引擎或 UI。

## D-20260723：选择性吸收 v2

吸收 Service/read model、批量快照、metadata/audio 并发分离、批量预览、状态策略、页面生命周期和资源库详情概念。

## D-20260730：T10 基于 RC2 重新移植

旧 PR #6 基于 RC1，与 RC2 下载页修复冲突。不得直接 merge；有效设计必须重新移植到 `main@9f292e7`，并保留 RC2 网速、完成项移除、批量刷新和四页导航。

## D-20260730：ChatGPT 不再推送 Git

ChatGPT 只读 GitHub并生成本地交付包。Codex负责拉取最新 main、应用包、Windows/Flet 验收以及一个 commit/一次 push/一个 PR，以减少远程逐文件操作和 CI 浪费。

## D-20260730：状态策略渐进启用

T10 提供显式状态迁移策略和测试，先用于 read model 能力判断。不得为了启用策略批量改旧数据库；写路径全面强制需单独小任务和历史兼容审计。

## 永久冻结边界

普通优化不得顺带开放 External Intake execute、正式迁移、VACUUM、backlog execute、T7 或生产批量状态写入。


## D-20260801：批量输入不再依赖原生 FilePicker

Flet 0.27.6 的 Windows FilePicker 在隔离最终 EXE 中未可靠弹出，且原生选档框不适合自动化验收。RC2 主入口改为应用内多行“批量粘贴”对话框；现有批量分类和确认模型继续复用。文件导入如需恢复，必须作为后续非阻塞次级入口单独验收。


## D-20260801：批量粘贴采用 Flet 0.27 对话框 API

RC2 批量粘贴必须使用 `page.open(dialog)` / `page.close(dialog)`；`page.dialog` 在 Flet 0.27.6 中只是无效的 Python 临时属性，不能作为弹窗宿主。批量预览仅以 orchestrator 的运行集合判断“当前活动”，页面缓存中的失败、历史和复核卡片必须交给持久化分类处理。
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
