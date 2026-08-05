# ARSM Suite 当前任务路线图


## PR1：直接源码 Windows 发布阻断验收

状态：`NO-GO / WAITING_WINDOWS_FULL_GATE`

- [x] 使用 V6 已应用完整源码替代补丁应用器；
- [x] 修复 cancelled 维护语义冲突；
- [x] focused pytest：49 passed；
- [x] 当前环境非 Flet 主体回归、导入烟测、维护专项、compileall、静态 release_check；
- [ ] Windows Python 3.12 + requirements-build；
- [ ] 完整 pytest（独立 basetemp）；
- [ ] release_check；
- [ ] PyInstaller one-folder + EXE 存在性；
- [ ] Flet 四页、按钮、DPI、托盘、关闭/退出实机验收；
- [ ] 自动和 GUI 门禁全绿后再决定 Git/PR。

> 更新时间：2026-07-30

## T10：Queue Service 与大队列优化

状态：`CONDITIONAL_GO / BATCH_PASTE_FIX_WAITING_WINDOWS`

已完成：

- [x] read models；
- [x] `DownloadService`；
- [x] 固定两次 SELECT 的队列快照；
- [x] 分页和状态筛选；
- [x] 批量 RJ 预览；
- [x] 独立 metadata scheduler；
- [x] 页面生命周期；
- [x] 显式状态策略；
- [x] RC2 网速、完成项移除、批量暂停/继续兼容；
- [x] 批量粘贴修复后本地测试桩 238/238；
- [x] 文档与 Codex 交接包。

Codex 待完成：

- [ ] 从最新 main 应用 overlay；
- [ ] Windows 真实 Flet compile/import/pytest；
- [ ] one-folder 构建；
- [ ] 200 任务临时数据库 UI 验收；
- [ ] 批量预览取消/确认验收；
- [ ] metadata_concurrency 保存和重启；
- [ ] 四页导航、最小化/恢复和正常退出；
- [ ] 一个 commit、一个 PR、CI；
- [ ] 返回 PR、CI、构建 SHA、日志和截图。

T10 完成标准：

```text
Linux/Windows CI 全绿
真实 Flet 0.27.6 导入通过
队列 200 项分页与筛选可用
批量预览确认前零副作用
metadata 峰值并发不超过配置
RC2 网速/完成移除/全部暂停继续无回归
正式数据零访问
```

## T11：桌面视觉与长期运行

- 4 个页面的实际截图和缩放；
- 连续三次启动/正常关闭；
- 30~60 分钟隔离运行观察；
- Defender、长路径和文件占用；
- 机器证据由 Codex采集，视觉由 ChatGPT复核。

## T12：真实网络与认证收口

- 研究真实 API 401 的具体端点和认证方式；
- 密钥仅保存在本机配置；
- 隔离小作品 metadata、封面、下载、暂停、恢复、完成；
- 不以 401 代替 PASS。

## T13：资源库详情体验

- 分类和排序；
- 右侧详情侧栏；
- 文件列表最多 200 项并标记截断；
- 复制 RJ/路径和打开目录；
- 不移动文件、不建第二数据库。

## T14：可选系统托盘

- 关闭到托盘/彻底退出；
- 打开、暂停全部、继续全部；
- 复用幂等 shutdown；
- 单独 Windows PR 和实机验收。

## 延后

- T7 正式目录整理：等待维护窗口；
- 播放器：等待下载、资源库和长期运行稳定。


## 2026-08-01 RC2 T10 隔离 Windows 验收更新

- 真实 Flet 0.27.6；compileall 和 git diff --check 均通过；pytest 为 230 passed、3 skipped（Windows 符号链接不可用）。
- RC2 ZIP：ARSM-Suite-0.9.0-rc.2-windows-x64.zip，57,247,433 bytes，195 项，SHA-256 a8961e730111519b49200ff7c82f06930fd81d0d30e6aaba19e829c37416fdb3。
- 七种队列筛选、分页回退、四页导航、metadata_concurrency 重启持久化、三轮正常关闭均已在隔离目录通过。
- 本机 127.0.0.1 限速 HTTP 流已完成真实下载、暂停、非空 .part 保留、Range 206 续传、最终文件与完成项移除验证。
- FilePicker 阻塞已改为应用内批量粘贴方案；代码完成但最终 Windows EXE 尚未复测。结论保持条件 GO。
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
### T12 更新（2026-08-01）

- 四个真实 RJ 的 metadata/tracks 在 Clash metadata proxy 下成功。
- `RJ01276295` 最小 MP3 已在隔离目录完整下载并精确校验大小；封面代理与音频 `download_proxy=None` 路由均已验证。
- 剩余：隔离环境的多文件专辑真实下载、暂停/恢复和长期外网稳定性；不得把小文件成功扩大为所有真实网络场景已验收。
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
## T15：真实网络与认证验收（2026-08-02，完成）

- 真实小作品已覆盖 metadata/cover 代理、音频直连、非空 `.part`、暂停稳定、206 续传、最终大小与 SHA-256。
- 401 与断网提示通过隔离本机 HTTP socket 验证；认证/网络恢复均能重新进入准备状态，失败路径零写入。
- 后续不再把 T15 当作 RC2 发布阻塞项；下一项为 T16：发布后小范围真实使用观察（保留正式数据边界）。

- T15 候选 one-folder 已在独立 `C:\tmp` 构建：64,734,852 bytes、203 条目、SHA-256 `bc680bc1d1b95aa6a9f5270901767d936994fe1ee9a7d7483b8d46f7f135a648`；未替换既有 GitHub Pre-release。
## 2026-08-02：RC3 候选发布准备

- PR #12（metadata 401/断网错误提示与 T15 验收）已通过 Ubuntu/Windows CI 并 squash merge 到 `main@3cb48ddd5e9ccd39ebba1e6c24c18e1071ba7080`。
- 新候选版本统一为 `0.9.0-rc.3`；不覆盖既有 `v0.9.0-rc.2` 标签或 Pre-release。
- 发布前仍需完成 RC3 全量测试、Windows one-folder 构建、标签工作流与附件 SHA-256 核验。
## T16：RC3 发布后小范围真实使用观察（已完成）

- RC3 已发布为 Pre-release：`v0.9.0-rc.3` → `main@894347bf917b317e3eb0e5555afb12b68b9d2210`；正式附件和 SHA-256 已核验。
- 使用 7 个明确指定的 RJ 观察 metadata、封面代理、音频直连、并发、暂停/继续、失败提示、完成移出队列、托盘及退出生命周期。
- 不进行全库扫描、目录整理、迁移、VACUUM 或 External Intake；`E:\arsm`、正式数据库和既有任务全程零接触。
- T16 结束后再决定是否有必要提交运行观察文档或开始功能修复；不把单次网络波动直接定性为产品缺陷。
### T16 中期状态

- 真实网络已完成 7/7 metadata 与 4 个受控音频；余下观察为 45 分钟运行采样、RJ01589930 的单项复测及正常退出检查。
- 当前不进入功能开发；若单项取消能稳定复现，下一任务才建立最小修复与回归用例。
### T16 结论（PASS_WITH_NOTES）

- 真实 metadata、代理边界、直连音频、受控多作品文件完成和长时稳定性均已取得证据。
- 不再把 T16 作为 RC3 使用门槛；后续仅在用户反馈真实异常时建立最小复现和修复任务。
- 采样 harness 的 SQLite 快照阻塞属于验收工具改进项，不进入 RC3 产品回归范围。

## PR1 直接源码候选：下一门槛

- 已完成：维护语义修复、Windows 自动门禁、PyInstaller、基础 GUI 与托盘退出生命周期。
- 待完成：在用户实际 125%/150%/200% 显示缩放下复核界面裁切与重叠。
- 通过后：在 codex/pr1-release-blocker-direct-source 创建一个提交、一次 push、一个 Draft PR；CI 与人工审查通过前不合并、不打标签、不发布。
## 2026-08-03：1.0.0 正式发布候选

- 版本统一为 1.0.0，新增 Inno Setup x64 安装器、固定 AppId 和 SHA-256 输出。
- 运行数据与安装目录分离：安装版位于 %LOCALAPPDATA%\Programs\ARSM Suite，数据位于 %LOCALAPPDATA%\ARSM Suite；便携版保持同目录数据行为。
- 最终回归：299 passed, 3 skipped；跳过项均为 Windows 环境无法创建符号链接。
- Windows 隔离验收：安装、启动、--shutdown 协作退出、运行中卸载、用户数据保留及零残留进程均通过。
- 最终安装器 SHA-256：2a7df244d6c07d289c7dea3a9788a271c48b6eb33f296b4a5de81e8c27b171e6。
- 当前状态：等待 Git PR、CI、合并、v1.0.0 标签和正式 GitHub Release；正式 E:\arsm 与既有运行数据零接触。

## v1.0.1（Issue #20 + #19）：PR #21 Draft，待真实验收

状态：`NO-GO / WAITING_REAL_GUI_AND_STRESS`

已完成：

- [x] P0-A UI 背压（`UiDispatcher` + 预算化 dispatch）；
- [x] P0-B 固定 worker 池（`DownloadWorkerPool`）；
- [x] P0-C 签名 URL 单飞刷新 + `SignedUrlExpired`（400/401/403）；
- [x] P0-D 磁盘核验进度（`verified_download_progress`）；
- [x] #19 下载页稳定列表 + 右侧文件树详情面板；
- [x] PR #21 审查 7 项 NO-GO 全部修复：
  - [x] `ensure_refreshed_once` 真单飞；
  - [x] refresh/transport budget 分离 + 二次签名 fail-closed + 日志脱敏；
  - [x] 磁盘核验移出 UI 线程 + generation token；
  - [x] UI 显示 verified 字节、`registered` 非终态、成功保持 `completed`、混合分母修复；
  - [x] UI 单调度器守卫 + 数量/时间双预算；
  - [x] 文件树/相对路径 key/失败原因/.part/每状态唯一按钮；
  - [x] 交付文档同步。
- [x] PR #21 第二轮审查 4 项全部修复：
  - [x] unknown-size 进度贯通 read model（`verified_progress`/known-size 字节）；
  - [x] 启动只执行一次磁盘核验；
  - [x] 同名文件实时更新按 track_id 解析；
  - [x] 文档顶部事实源与 head/SHA/370 passed 同步。
- [x] 全量回归：`368 passed, 3 skipped`；release_check `ready: true`。

待完成（需 Windows 宿主，通过前不转 Ready）：

- [ ] 真实 GUI / DPI 125–200% / 托盘 / 退出验收；
- [ ] 9 任务约 2700 文件 30 分钟压力验收；
- [ ] 300 个集中 HTTP 400 场景；
- [ ] 远端完整 pytest/CI、release_check、PyInstaller；
- [ ] 验收通过后再决定是否转 Ready。