# ARSM Suite 当前状态

> 更新时间：2026-08-02 22:03 +08:00
> PR1 修复基线：`main@50346f9da9a5d24dda99f7d8c6c21e2f9210c1a6`
> 当前版本：`0.9.0-rc.3`（PR1 直接源码候选，未发布）
> 当前阶段：`PR1 自动门禁待 Windows/Flet 完整复验；NO-GO`

## 0. PR1 直接源码修复状态

- 输入事实源：V6 已应用的完整隔离 worktree 源码快照，原始 ZIP SHA-256 为 `58313ef72b108984714abf8a5aa2fb02bd8a81fcaceb966ed8f1fec16619e3b6`。
- 不再维护 `apply_fixes.py` 或文本锚点；本轮直接修改真实应用后源码与真实测试。
- 已将维护安全集合拆分为：
  - `MAINTENANCE_BLOCKING_STATUSES`：活动或可恢复状态，阻止 VACUUM/队列维护；
  - `METADATA_PROTECTED_STATUSES`：上述状态加 `cancelled`，保护显式重试所需缓存；
  - `TERMINAL_QUEUE_STATUSES`：包含 `cancelled`，作为终态统计。
- 已验证 cancelled 行不会阻止 VACUUM，VACUUM 后 cancelled 下载记录和 metadata cache 均保留。
- 本地结果：focused `49 passed`；非 Flet 主体 `234 passed`；非 UI import smoke `19 passed`；维护专项 `10 passed`；compileall PASS；`release_check --skip-tests` PASS。
- 当前容器无法安装锁定的 `flet==0.27.6`，因此完整 pytest、Windows one-folder、GUI/DPI/托盘/退出必须由 Codex 在隔离 Windows 环境执行。
- 正式 `E:\arsm`、`history.db`、`config.json`、`queue.json`、现有 `.part` 均未接触。
- 结论：**NO-GO**；全门禁通过前禁止提交、push、PR 和发布。

## 1. 已确认发布事实

- `0.9.0-rc.1` Release、ZIP 和 SHA-256 已通过；
- Windows 11 隔离环境已验证三次正常启动/关闭、真实元数据、真实文件列表、非空 `.part`、暂停、关闭重启、恢复和最终非空 MP3；
- “全部暂停”和“全部开始”核心行为有效；旧缺陷是 UI 汇总未刷新；
- RC2 已修复汇总、网速、完成项移除和批量按钮状态，并删除成就页；
- RC2 GitHub Ubuntu/Windows CI：211/211 PASS。

## 2. T10 本地实现

### Queue Service

- 不可变 `DownloadQueueItem/DownloadQueueSummary/DownloadQueuePage`；
- `DownloadService` 只复用现有 `LibraryVault`，不创建第二连接；
- 队列快照固定两次 SELECT，不按卡片查询；
- 分页 1~200 项，默认 24；
- 筛选：活动、下载中、等待、暂停、失败、完成、全部；
- completed 默认不占活动队列。

### 批量输入

- 主入口改为应用内“批量粘贴”多行对话框，不再依赖 Windows 原生 FilePicker；
- 支持 RJ、纯数字、ASMR.one URL；
- 预览阶段零写入、零建目录、零网络；
- 识别输入重复、活动任务、SQLite 队列、资源库索引、完成历史和同前缀目录；
- 确认后才逐项入队，并明确解释“提交 10 个但只有 9 个不同 RJ”的原因。

### Metadata Scheduler

- 独立 FIFO worker queue；
- 默认 2，限制 1~8；
- 与 work/file 并发独立；
- 100 个作业峰值并发实测为 2；
- shutdown 幂等，关闭时取消未完成 metadata 作业。

### UI 生命周期

- 下载页隐藏后停止卡片重绘，后台下载继续；
- 返回下载页立即读取 SQLite 快照；
- 资源库离开后使正在返回的旧查询结果失效；
- Tools 和 Settings 只在激活时执行必要刷新。

### 状态策略

- 新增显式合法/非法迁移规则；
- read model 的按钮能力使用该策略；
- 不批量迁移旧状态，不修改 schema；
- 全写路径强制 enforcement 留待后续小任务，避免破坏历史兼容。

## 3. 验证

```text
compileall：PASS
批量粘贴修复本地测试桩：238/238 PASS
Windows 修复前基线：231 passed，3 skipped
10/50/100/200 个任务：固定 2 次 SELECT
100 个 metadata 作业：峰值并发 2
正式 DB：未访问
真实 E:\arsm：未访问
旧 .part：未修改
数据库 schema：未修改
```

批量粘贴新增测试在临时 Flet 接口桩下通过；该桩不进入交付包。真实 Flet 0.27.6 下只需复测批量粘贴对话框、取消零副作用和确认仅加入 ready 项。

## 4. Git 状态

- ChatGPT 本轮没有推送、没有创建远端分支、没有更新 PR；
- 旧 Draft PR #6 基于 `main@9f292e...`，与 RC2 直接冲突，不应直接 merge；
- Codex 应从最新 `main@9f292e7` 新建一个分支，应用 T10 overlay，形成一个 commit 和一个 PR；
- 旧 PR #6 可在新 PR 建立后关闭并注明 superseded。

## 5. Codex 必做

1. 在现有隔离 worktree 应用 `ARSM-T10-Batch-Paste-Fix-Overlay.zip`；
2. 使用真实 Flet 0.27.6 跑 import、compileall、pytest 和 `git diff --check`；
3. 重新构建 Windows one-folder 并更新 ZIP/SHA-256；
4. 验证“批量粘贴”打开应用内多行对话框，不触发原生 FilePicker；
5. 混合输入取消后 works/downloads/队列/目录零变化；
6. 确认后仅 ready 项入队，预览统计与实际一致；
7. 快速复核筛选、暂停/继续、设置和三次关闭；
8. 全部通过后一个 commit、一次 push、一个新 PR。

## 6. 继续冻结

正式迁移、External Intake execute、VACUUM、backlog execute、T7 和任何生产批量状态写入继续冻结。


## 2026-08-01 RC2 T10 隔离 Windows 验收更新

- 真实 Flet 0.27.6；compileall 和 git diff --check 均通过；pytest 为 230 passed、3 skipped（Windows 符号链接不可用）。
- RC2 ZIP：ARSM-Suite-0.9.0-rc.2-windows-x64.zip，57,247,433 bytes，195 项，SHA-256 a8961e730111519b49200ff7c82f06930fd81d0d30e6aaba19e829c37416fdb3。
- 七种队列筛选、分页回退、四页导航、metadata_concurrency 重启持久化、三轮正常关闭均已在隔离目录通过。
- 本机 127.0.0.1 限速 HTTP 流已完成真实下载、暂停、非空 .part 保留、Range 206 续传、最终文件与完成项移除验证。
- 原生 FilePicker 现场入口无法可靠弹出，已决定退出 RC2 主链路；当前源码改为应用内“批量粘贴”对话框并新增零副作用/仅 ready 入队回归测试。该修复尚未由真实 Flet 0.27.6 最终 EXE 验证，因此维持条件 GO；不提交、不推送、不建 PR、不发布。
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
## 2026-08-01 T12 隔离真实网络小文件验收

- Clash HTTP 代理 `127.0.0.1:7897` 可用；`RJ01276295`、`RJ01271436`、`RJ01261242`、`RJ01242844` 的 metadata 与 tracks 请求均成功。
- 使用 `RJ01276295` 的最小 MP3 做端到端验证：metadata 与封面明确使用 `http://127.0.0.1:7897`，封面响应 `200`；音频 `download_proxy=None`，响应 `200`。
- 音频临时文件只写入隔离目录 `_t12-network-check-20260801`：预期、接收和落盘均为 `1,627,577` bytes，大小精确一致；未创建下载任务或写入正式数据。
- 小文件真实链路 PASS；多文件完整下载、外网暂停恢复和长期稳定性仍属于后续 T12/T11，RC2 暂不发布。
### T12 并发 metadata 验证补充

- 使用四个用户提供的 RJ，在 `metadata_concurrency=2` 下只读请求 metadata 与 tracks。
- 实测峰值并发 `2`，四项 metadata 和 tracks 均成功；没有创建下载任务或启动音频 worker。
### T12 真实外网暂停/续传补充（2026-08-01）

- 以 `RJ01276295` 的 `1,627,577` bytes MP3 在隔离目录进行真实暂停/恢复：先落盘 `.part=524,288` bytes，再以 `Range: bytes=524288-` 续传。
- 续传响应 `206`，`Content-Range: bytes 524288-1627576/1627577`；追加 `1,103,289` bytes 后最终大小精确为 `1,627,577` bytes。
- 下载通道 `download_proxy=None`。完成后删除临时音频，只保留 JSON 证据；没有创建 SQLite 下载任务。
- 曾尝试约 14.9MB 文件，但受当前外网吞吐量影响在验收命令时限内未完成；已停止测试进程并清理遗留 `.part`，不将其计为通过或产品缺陷。
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
## 2026-08-02 T13 资源库详情体验完成（隔离验收）

- 新增资源库海报卡片的右侧只读详情：标题、社团、RJ、标签、文件/音频/容量统计及文件列表；
- 文件枚举仅在选择单张专辑后后台执行，最多显示 200 项并提示截断；
- 新增分类、排序、复制 RJ/路径和统一的打开目录入口；
- 真实 Flet 0.27.6：资源库定向测试 `10 passed`，全量 `241 passed, 3 skipped`（Windows 不支持符号链接）；
- 真实隔离窗口已验收分类、排序、详情和正常关闭；未读取或写入 `E:\arsm`、正式数据库、正式队列。
## 2026-08-02 T14 系统托盘与退出生命周期

- Windows 标题栏关闭在托盘可用时隐藏窗口，下载服务保持运行；托盘菜单提供打开窗口、全部暂停、全部继续与彻底退出。
- 托盘初始化是可选的：若系统托盘后端不可用，关闭会回退到既有的幂等安全退出，不会遗留下载器进程。
- 托盘回调一律通过 UI 消息队列执行，避免托盘线程直接操作 Flet 控件；彻底退出会停止托盘、后台 worker、网络客户端与 SQLite。
- 隔离 Flet 实机已确认关闭后应用窗口消失且 Python/Flet 仍存活；生命周期测试和全量回归通过。正式环境零接触。
- T14 one-folder 构建：ARSM-Suite-0.9.0-rc.2-windows-x64.zip，64,732,978 bytes、203 entries、SHA-256 3373fe17e5b55e4b346e3d0761146dc53fd74bde4d22f599a3b225096d1ec2df；校验文件一致且含 ARSM-Suite.exe。

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

- T15 候选 one-folder 已在独立 `C:\tmp` 构建：64,734,852 bytes、203 条目、SHA-256 `bc680bc1d1b95aa6a9f5270901767d936994fe1ee9a7d7483b8d46f7f135a648`；未替换既有 GitHub Pre-release。
## 2026-08-02 RC3 候选构建验收

- 全量自动回归：`245 passed, 3 skipped`；3 项 skipped 均为当前 Windows 无法创建 symbolic link。
- 独立 one-folder：`C:\tmp\arsm-rc3-onefolder-20260802\ARSM-Suite-0.9.0-rc.3-windows-x64.zip`。
- ZIP：64,735,175 bytes、203 个条目，包含 `ARSM-Suite.exe`。
- SHA-256：`d06a4ddb2ae9642526563ef27a26f429418c0cb713dd7728e615d0bca108964e`，与 `.sha256` 一致。
- EXE FileVersion/ProductVersion：`0.9.0-rc.3`。现有 RC2 Pre-release 未修改。
## 2026-08-02 RC3 已发布；T16 已完成

- RC3 已作为 GitHub Pre-release 发布：`v0.9.0-rc.3` 精确指向 `main@894347bf917b317e3eb0e5555afb12b68b9d2210`；未改动 RC2 标签或 Release。
- 标签工作流 `release-build.yml` 成功：`https://github.com/5788324/arsm-downing/actions/runs/30730199281`。
- 官方 Windows ZIP：`ARSM-Suite-0.9.0-rc.3-windows-x64.zip`，65,208,001 bytes、212 项，含 `ARSM-Suite.exe`；SHA-256 `b1bdee2ac5c3fa792d4747808a0d478d78b92319ae5b49de647d2837e7b87f33`，与发布校验文件及 GitHub 资产摘要一致。
- T16 已使用 7 个用户指定 RJ 启动小范围真实使用观察；本轮只观察明确提交的任务，不扫描、移动或整理 `E:\arsm`。
### T16 中期真实观察（2026-08-02 16:06）

- 7 个用户指定 RJ 均完成真实 metadata；受控计划只下载 5 个最小音频，合计 43,557,391 bytes，另外 2 个仅保留 metadata，避免超出小范围上限。
- 音频直连日志已确认 HTTP 200；`RJ01616587`（9,843,959 bytes）、`RJ01606670`（9,654,848 bytes）、`RJ01632789`（209,715 bytes）和 `RJ01627434`（19,008,630 bytes）均完成并注册。
- `RJ01589930` 在受控队列首项出现一次取消，保留 queued 以待单独复测；不把验收脚本并发筛选问题定性为正式程序缺陷。
- 45 分钟 worker 继续在 `C:\tmp\ARSM-T16-RC3\ControlledRuntimeDataV2` 采样；正式 `E:\arsm` 与既有任务零接触。
### T16 最终结论（2026-08-02）

- 7/7 指定 RJ 的真实 metadata 成功；5 个受控最小音频完成并注册：RJ01589930 4,840,239 bytes、RJ01616587 9,843,959 bytes、RJ01606670 9,654,848 bytes、RJ01632789 209,715 bytes、RJ01627434 19,008,630 bytes。
- 每个完成文件的 SQLite downloaded/total 与计划大小一致；metadata/cover 走 `http://127.0.0.1:7897`，音频日志确认 direct/HTTP 200。
- 长时观察运行超过 52 分钟，worker CPU 3.97 秒、工作集约 52 MiB，下载完成后无状态漂移或 stderr 错误。自制采样 harness 卡在首个 SQLite 快照，已停止；单独的 RC3 `Orchestrator` 启动/正常 shutdown 验证通过，因此不把 harness 问题定性为产品缺陷。
- T16：**PASS_WITH_NOTES**。正式 `E:\arsm`、既有 RC2 实例、正式数据库和队列全程零接触。

## 2026-08-02 PR1 直接源码候选：Windows 验收完成（条件 GO）

- 维护语义已拆分为维护阻断、metadata 保护和终态队列三个集合；已取消任务不阻止 VACUUM/队列预览，但继续保护 metadata 以支持显式重试。
- 在全新隔离 Python 3.12 环境：focused 49 passed，full 294 passed, 3 skipped，elease_check --skip-tests ready=true，PyInstaller one-folder 与 EXE 非空通过。
- 隔离 EXE：8,320,551 bytes，SHA-256 6c84d11e7b028cbb96ffa5b58cba56c91ae09ceb7fcc2af8abaebd3c928ad580。
- GUI：四页导航、批量粘贴取消、维护保护可见性和三轮启动/关闭通过；托盘彻底退出后无 ARSM/Flet/Python 残留。
- 未改变 main、正式 E:\arsm、正式数据库、队列、任务或 .part。高 DPI（125%/150%/200%）视觉检查仍需在用户显示缩放下完成。