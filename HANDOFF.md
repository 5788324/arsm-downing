# ARSM Suite T10 交接


## 2026-08-02 PR1 直接源码候选交接

- 唯一源码事实源：基于 `main@50346f9da9a5d24dda99f7d8c6c21e2f9210c1a6`、已成功应用 V6 的完整 worktree 快照。
- 本轮不再运行应用器；Codex 直接解压完整源码并运行 `WINDOWS_VALIDATION.ps1`。
- 已解决唯一聚焦失败：cancelled 不阻止 VACUUM，但继续保护 metadata cache。
- 自动门禁全部通过前，不得提交、push、创建 PR 或发布。
- 正式数据边界：禁止访问 `E:\arsm`、正式 history/config/queue、现有任务与 `.part`。

## 基线

```text
仓库：5788324/arsm-downing
当前基线：main@3cb48ddd5e9ccd39ebba1e6c24c18e1071ba7080
当前候选版本：0.9.0-rc.3
交付方式：本地 overlay，不由 ChatGPT 推送
```

## Codex 输入

- `ARSM-T10-Batch-Paste-Fix-Overlay.zip`
- `T10_BATCH_PASTE_CODEX_TASK.md`
- `T10_BATCH_PASTE_LOCAL_TEST_REPORT.json`

## 操作顺序

1. 保留现有 `codex/t10-queue-service` 隔离 worktree；
2. 运行 overlay 中 `VERIFY_T10_BATCH_PASTE_PACKAGE.ps1`；
3. 运行 `APPLY_T10_BATCH_PASTE_FIX.ps1`，脚本会校验被修改文件的导出源码哈希；
4. 使用真实 Flet 0.27.6 运行 import、compileall、pytest 和 `git diff --check`；
5. 重新构建 Windows one-folder；
6. 只补齐“批量粘贴”取消/确认 GUI 验收并做最小回归；
7. 更新 `docs/WINDOWS_T10_ACCEPTANCE.md`；
8. 全部通过后一个 commit、一次 push、一个新 PR。

## 禁止

- 不直接合并旧 PR #6；
- 不访问正式 `history.db`、`E:\arsm` 或现有 100+ 任务；
- 不修改 200/206/416 和 `.part` 核心；
- 不执行 External Intake、迁移、VACUUM、backlog 或 T7；
- 不让用户手工测试；
- 不在失败后做零碎多次推送。

## 必交证据

- 分支、commit、PR URL；
- Ubuntu/Windows CI；
- `pytest` 总数；
- Windows 构建 ZIP 和 SHA-256；
- 下载页活动/下载中/等待/暂停/失败/完成筛选截图；
- 第 1 页和第 2 页截图；
- 批量粘贴输入、预览、取消零副作用与确认仅 ready 入队截图；
- metadata_concurrency 保存重启；
- 正常关闭后进程清单；
- 正式环境零接触声明。


## 2026-08-01 RC2 T10 隔离 Windows 验收更新

- 真实 Flet 0.27.6；compileall 和 git diff --check 均通过；pytest 为 230 passed、3 skipped（Windows 符号链接不可用）。
- RC2 ZIP：ARSM-Suite-0.9.0-rc.2-windows-x64.zip，57,247,433 bytes，195 项，SHA-256 a8961e730111519b49200ff7c82f06930fd81d0d30e6aaba19e829c37416fdb3。
- 七种队列筛选、分页回退、四页导航、metadata_concurrency 重启持久化、三轮正常关闭均已在隔离目录通过。
- 本机 127.0.0.1 限速 HTTP 流已完成真实下载、暂停、非空 .part 保留、Range 206 续传、最终文件与完成项移除验证。
- 原生 FilePicker 已从主入口移除，改为应用内批量粘贴对话框；等待最终 EXE 验证取消零副作用和确认仅加入 ready 项。验证前维持条件 GO。
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
## 2026-08-02：RC3 候选发布准备

- PR #12（metadata 401/断网错误提示与 T15 验收）已通过 Ubuntu/Windows CI 并 squash merge 到 `main@3cb48ddd5e9ccd39ebba1e6c24c18e1071ba7080`。
- 新候选版本统一为 `0.9.0-rc.3`；不覆盖既有 `v0.9.0-rc.2` 标签或 Pre-release。
- 发布前仍需完成 RC3 全量测试、Windows one-folder 构建、标签工作流与附件 SHA-256 核验。
## 2026-08-02 RC3 候选构建验收

- 全量自动回归：`245 passed, 3 skipped`；3 项 skipped 均为当前 Windows 无法创建 symbolic link。
- 独立 one-folder：`C:\tmp\arsm-rc3-onefolder-20260802\ARSM-Suite-0.9.0-rc.3-windows-x64.zip`。
- ZIP：64,735,175 bytes、203 个条目，包含 `ARSM-Suite.exe`。
- SHA-256：`d06a4ddb2ae9642526563ef27a26f429418c0cb713dd7728e615d0bca108964e`，与 `.sha256` 一致。
- EXE FileVersion/ProductVersion：`0.9.0-rc.3`。现有 RC2 Pre-release 未修改。
## 2026-08-02 RC3 已发布；T16 已完成

- 正式 Release：`https://github.com/5788324/arsm-downing/releases/tag/v0.9.0-rc.3`（Pre-release）。标签和 main 均为 `894347bf917b317e3eb0e5555afb12b68b9d2210`。
- 官方 ZIP 已核验：65,208,001 bytes、212 项、包含 `ARSM-Suite.exe`；SHA-256 `b1bdee2ac5c3fa792d4747808a0d478d78b92319ae5b49de647d2837e7b87f33`。
- 当前任务：以用户指定的 7 个 RJ 做小范围真实下载观察。记录真实状态，不伪造网络通过；禁止扩展到全库或既有任务。
### T16 中期证据

- 隔离目录 `C:\tmp\ARSM-T16-RC3\ControlledRuntimeDataV2`：7 个 RJ metadata 成功，5 个受控音频总上限 43,557,391 bytes。
- 已注册完成：RJ01616587 9,843,959 bytes、RJ01606670 9,654,848 bytes、RJ01632789 209,715 bytes、RJ01627434 19,008,630 bytes；音频日志为 direct/HTTP 200。
- RJ01589930 queued，曾发生一次取消，需在本轮结束前单项复核。
### T16 最终交接

- 7/7 metadata、5 个最小音频已完成；文件大小：RJ01589930 4,840,239、RJ01616587 9,843,959、RJ01606670 9,654,848、RJ01632789 209,715、RJ01627434 19,008,630 bytes。
- metadata/cover=`127.0.0.1:7897`，audio=direct，所有完成文件均 HTTP 200/SQLite registered。
- 长时观察超过 52 分钟稳定；harness SQLite 快照卡住，隔离停止后数据库锁释放。独立 Orchestrator shutdown PASS，因此 T16 结论为 PASS_WITH_NOTES。

## PR1 直接源码候选交接（2026-08-02）

- 可审查分支：codex/pr1-release-blocker-direct-source，基线 main@50346f9da9a5d24dda99f7d8c6c21e2f9210c1a6。
- Windows 自动门禁：focused 49 passed，full 294 passed/3 skipped，release check、PyInstaller 与 EXE 通过。
- GUI：四页、批量粘贴取消、工具安全冻结、三轮启动/关闭和托盘退出后的无残留通过。证据位于隔离验收目录，未接触正式数据。
- 下一步：完成用户设备高 DPI 视觉复核后，创建单一提交、推送并建立 Draft PR；不得直接改 main 或发布。
## 2026-08-03：1.0.0 正式发布候选

- 版本统一为 1.0.0，新增 Inno Setup x64 安装器、固定 AppId 和 SHA-256 输出。
- 运行数据与安装目录分离：安装版位于 %LOCALAPPDATA%\Programs\ARSM Suite，数据位于 %LOCALAPPDATA%\ARSM Suite；便携版保持同目录数据行为。
- 最终回归：299 passed, 3 skipped；跳过项均为 Windows 环境无法创建符号链接。
- Windows 隔离验收：安装、启动、--shutdown 协作退出、运行中卸载、用户数据保留及零残留进程均通过。
- 最终安装器 SHA-256：2a7df244d6c07d289c7dea3a9788a271c48b6eb33f296b4a5de81e8c27b171e6。
- 当前状态：等待 Git PR、CI、合并、v1.0.0 标签和正式 GitHub Release；正式 E:\arsm 与既有运行数据零接触。

## v1.0.1 交接（2026-08-06）——PR #21 Draft

### 分支与提交

- 分支：`fix/v1.0.1-download-freeze-ui`（base `main@b628c86`）。
- 提交：`872ef7c`（P0 #20）、`dde1ed9`（#19）、`98e3b07`（bump 1.0.1）。
- PR：`https://github.com/5788324/arsm-downing/pull/21`（Draft，Fixes #19 #20）。

### PR #21 审查（NO-GO）修复已完成

- `SignedUrlRefresher.ensure_refreshed_once()`：并发 403 共享同一刷新 future；成功复用、失败返回同一失败。
- `download_file`：refresh/transport budget 分离，`refresh_used`，二次签名错误 fail-closed；`retry_count=1` 也尝试新 URL；日志不输出 `fresh_url`。
- `refresh_queue_async`/`load_queue`：经 `run_blocking` 离开 UI 线程 + generation token 丢弃过期。
- `_update_compact_card`/detail：显示 `verified_bytes`；`registered` 非终态；orchestrator 成功保持 `completed`；`verified_download_progress` 修复 unknown+known 混合分母。
- `ui/app_base.py`：单调度器守卫（`_ui_schedule_lock`）+ 数量/时间双预算 + `await asyncio.sleep(0)`。
- 详情面板：文件树（相对路径 key、目录缩进）、失败原因、`.part` 状态、重复名不碰撞、每状态唯一按钮。
- 全量回归：`367 passed, 3 skipped`。

### 第二轮审查 4 项（2026-08-06 已修复）

1. **unknown-size 进度贯通 read model**：`DownloadQueueItem` 新增 `verified_known_bytes/verified_expected_bytes/verified_progress`，`progress` 优先返回磁盘核验的 known-size 比率；卡片/详情的进度条与容量都用该值；`completed/registered` 展示完成态服从磁盘核验，不再无条件强制 100%。
2. **启动单次磁盘核验**：`load_queue()` 并入 `refresh_queue_async` 同一管道；子类构造末尾不再二次 `reload_queue_from_database`。初始化后 pending query 恰为 1，后续请求合并。
3. **同名文件实时更新**：`update_track_progress` 维护 track_id 键控 `_live_tracks`；`_file_details` 以 download id 优先映射；实时更新按 track_id 解析，同名不同目录各自更新，重绘不重复。
4. **文档事实源**：CURRENT_STATE 顶部状态、head SHA、远端 Windows CI `371 passed`、最新构建 SHA `dfa29fc1…` 已同步。
- 全量回归：`368 passed, 3 skipped`。

### 第三轮审查 2 组（2026-08-06 已修复）

1. **实时总进度统一**：`_get_progress_value`（卡片与详情共用）改为 track_id 键控 `_live_tracks` 聚合，只计 known-size 字节分子/分母，同名文件分别统计；live 数据建立后优先于旧磁盘快照，快照仅作基线。
2. **registered/completed 磁盘不完整降级**：`apply_disk_verification` 增加 `status_filter`；磁盘核验未齐全的 `completed/registered` 下载作品降级为 `partial`（非终态、可恢复、黄色警示），不再显示绿色 100%；正式数据库未改动。
- 全量回归：`373 passed, 3 skipped`；PyInstaller SHA-256 `fada0cc4afabdaabf33871987559d5ab4316e4a2acf6a746b1f20cf17cb612b0`。

### 第四轮审查 4 项（2026-08-06 已修复）

1. **恢复任务全作品实时总进度**：`_live_tracks` 改为完整 per-track 基线（新一轮准备/恢复时由 `update_work_status` 失效，首个进度事件用 DB 全部文件重建，含已完成文件）；恢复 9 完成 + 1 续传显示 90% → 95% → 100%。
2. **mixed known/unknown 完整性判定**：`_disk_confirms_complete` 要求 `complete_files == file_count`、无 overage、known-size 100%；已知完整 + 未知缺失不误判完成。
3. **partial 走 resume/reconcile**：`partial` 按钮调用 `resume_download`（`_resume_one`/`resume_job`），`library_index` 已存在也不会被 duplicate guard 拦截。
4. **Working 核验后分页**：`DownloadService.fetch_working_page` over-fetch → 核验降级/丢弃 → 再分页并重算 `total_items/page_count`。
- 全量回归：`377 passed, 3 skipped`；PyInstaller SHA-256 `169d71fe808d14690a0edeb8d5a9b31213e88ee8b674008ba2f1c914e52d7444`。
- CI（head `facf351`）：Windows **380 passed**；Ubuntu **379 passed, 1 skipped**。Ubuntu 的 15 分钟超时两次均为 runner 资源拥挤（同一 head 曾 51s 通过），已在 `tests/conftest.py` 加入 Linux 专属 60s 单测超时守卫作防护。

### 交接给下一位执行者

1. 保持 Draft，不转 Ready、不合并、不打标签、不发布。
2. 在本分支完成真实验收（需 Windows 宿主）：
   - 真实 GUI / DPI 125–200% / 托盘 / 退出；
   - 9 任务约 2700 文件 30 分钟压力验收；
   - 300 个集中 HTTP 400 场景；
   - 远端完整 pytest/CI、release_check、PyInstaller。
3. 验收通过后再讨论是否转 Ready。

## 2026-08-19 用户体验收口交接

- 在 PR #21 同一分支集中修复：取消后卡片和断点恢复入口、终态速度/ETA 清零、空资源库设置引导、设置页双保存入口、系统工具新手文案、页内导航生命周期和按应用目录隔离的 Windows shutdown signal。
- 每项生产改动均补充对应测试；提交前必须运行定向测试、完整 pytest、compileall、release_check 和 `git diff --check`。
- 该收口不访问正式 `E:\arsm`，不执行 External Intake、迁移、VACUUM、backlog 或媒体文件操作。
- `asmr.one` 状态标签与“下载到 ARSM”已建立独立任务文档：[`docs/BROWSER_EXTENSION_TASKS.md`](docs/BROWSER_EXTENSION_TASKS.md)。它是新功能，必须在 PR #21 结束后从主线另开分支，不得塞入 v1.0.1 修复候选。
