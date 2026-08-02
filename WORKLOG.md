# ARSM Suite 当前阶段工作日志

历史日志见 `docs/archive/WORKLOG_20260627_20260721.md`。

## 2026-07-23：RC2 下载页修复

- Windows 实机证明全部暂停/开始核心有效；
- 修复汇总滞后、增加全局/作品网速；
- 完成项立即移出活动队列；
- 删除统计与成就页；
- GitHub Ubuntu/Windows 211/211 PASS；
- 合并提交：`9f292e7947804f2e4d53290039501f79c6d1805d`。

## 2026-07-30：TAKEOVER-T10 本地开发

### 执行方式

- 只读 GitHub；
- 未推送、未创建远端 PR；
- 从 RC1 Bundle 重建源码，并通过 GitHub 只读文件核对 RC2 当前文件；
- 审查旧 PR #6，仅吸收有效设计，不直接合并旧分支。

### 完成

- `core/read_models.py`；
- `core/services/download_service.py`；
- `core/metadata_scheduler.py`；
- `core/state_policy.py`；
- 配置和设置页增加 `metadata_concurrency`；
- Orchestrator 接入独立 metadata worker queue；
- 下载页接入队列快照、分页、筛选和批量预览；
- RC2 全局/作品网速、完成项即时移除和批量按钮保持；
- 四页 active/inactive 生命周期；
- 新增性能、并发、状态、UI 和生命周期回归测试。

### 测试

```text
compileall：PASS
pytest：232/232 PASS
10/50/100/200 个任务：2 次 SELECT
100 个 metadata 作业：峰值 2
```

本地 UI 测试使用临时 Flet 接口桩，该桩不进入交付包。真实 Flet 和 Windows 由 Codex验收。

### 数据影响

```text
正式数据库：未访问
E:\arsm：未访问
现有任务：未访问
数据库 schema：未改变
文件移动/删除：无
Git 远端写入：无
```

### 下一步

Codex拉取最新 main，应用 overlay，完成 Windows/Flet/构建/CI 和最终 PR。


## 2026-08-01 RC2 T10 隔离 Windows 验收更新

- 真实 Flet 0.27.6；compileall 和 git diff --check 均通过；pytest 为 230 passed、3 skipped（Windows 符号链接不可用）。
- RC2 ZIP：ARSM-Suite-0.9.0-rc.2-windows-x64.zip，57,247,433 bytes，195 项，SHA-256 a8961e730111519b49200ff7c82f06930fd81d0d30e6aaba19e829c37416fdb3。
- 七种队列筛选、分页回退、四页导航、metadata_concurrency 重启持久化、三轮正常关闭均已在隔离目录通过。
- 本机 127.0.0.1 限速 HTTP 流已完成真实下载、暂停、非空 .part 保留、Range 206 续传、最终文件与完成项移除验证。
- 批量预览取消/确认的现场 UI 证据仍缺失：当前 Flet 桌面壳自动化无法稳定发送文本输入或文件选择结果。结论保持条件 GO；不提交、不推送、不建 PR、不发布。
- 正式 history.db、config.json、queue.json、E:\arsm、现有任务和正式 .part 均未访问或修改。


## 2026-08-01：批量粘贴阻塞修复

### 输入事实

- Codex 提供 `ARSM-T10-CURRENT-SOURCE-CLEAN.zip`，SHA-256 `2acf0d616a090e0e2eb16130b0c488f02910e9fff44ea0a5c7fdd7f731587922`；
- 包含 340 个文件，未包含 Git、虚拟环境、构建、Evidence、数据库、配置、队列或 `.part`；
- 原生 Flet 0.27.6 FilePicker 在最终 EXE 中未可靠弹出，批量预览现场验收被阻塞。

### 修改

- 将“批量导入文件”替换为应用内“批量粘贴”；
- 多行 TextField 支持 RJ、纯数字、ASMR.one URL 和多种分隔符；
- 关闭输入对话框不触发分类、数据库、目录、网络或队列操作；
- 点击预览后继续复用现有完整分类模型；
- 确认时只对 `ready` 项调用 `start_download`；
- FilePicker 从 page.overlay 移除，不再进入 RC2 主链路；
- 重开输入对话框时不保留上次未提交文本。

### 自动验证

```text
compileall：PASS
pytest collection（临时 Flet 接口桩）：238
pytest（临时 Flet 接口桩）：238/238 PASS
新增 UI 回归：5 项
正式数据访问：无
Git 远端写入：无
```

临时 Flet 桩仅用于当前 Linux 容器，不进入交付包。最终真实 Flet 0.27.6 验收由 Codex完成。


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
## 2026-08-02 RC3 发布与 T16 收口

- PR #12 与 RC3 准备 PR #13 已合并，发布基线为 `main@894347bf917b317e3eb0e5555afb12b68b9d2210`。
- `v0.9.0-rc.3` 已创建为 Pre-release；Windows 构建工作流成功，正式附件的 ZIP、SHA-256、条目数及 `ARSM-Suite.exe` 均已独立核验。
- 发布资产：65,208,001 bytes、212 项、SHA-256 `b1bdee2ac5c3fa792d4747808a0d478d78b92319ae5b49de647d2837e7b87f33`。
- 启动 T16 小范围真实使用观察，样本：`RJ01589930`、`RJ01616587`、`RJ01606670`、`RJ01555813`、`RJ01533932`、`RJ01632789`、`RJ01627434`。
### T16 中期观察

- 7 个样本的 metadata 真实成功；5 个最小音频受 64 MiB 总量上限控制。
- 已完成 4 个直连文件：RJ01616587、RJ01606670、RJ01632789、RJ01627434；所有完成项的 SQLite downloaded/total 字节一致。
- RJ01589930 首项取消仍待复测；当前只记录事实，不创建产品缺陷结论。
### T16 最终收口

- 7/7 metadata 成功，5/5 受控音频完成并校验 SQLite 大小；总受控计划 43,557,391 bytes。
- 长时观察超过 52 分钟，CPU 3.97 秒、工作集约 52 MiB、无 stderr 错误；采样 harness 的 SQLite 快照卡住已隔离停止。
- 最小 RC3 `Orchestrator` 正常 shutdown 复核通过；T16 结论 PASS_WITH_NOTES，未发现可归因的产品缺陷。

## 2026-08-02 PR1：停止补丁应用器，转为完整源码直接修复

- 接收并核验 V6 已应用 worktree 源码 ZIP：SHA-256 `58313ef72b108984714abf8a5aa2fb02bd8a81fcaceb966ed8f1fec16619e3b6`。
- 在真实应用后源码复现聚焦结果：`48 passed, 1 failed`。
- 根因：单一 `ACTIVE_STATUSES` 同时承担“维护阻断”和“metadata 保留”两种不同语义，导致 cancelled 错误阻止 VACUUM。
- 直接修改 `core/tools_maintenance.py`：拆分维护阻断、缓存保护和终态队列集合；cancelled 不阻止 VACUUM/队列预览，但保护 metadata。
- 更新真实行为测试：VACUUM 实际执行成功，cancelled 下载行和 metadata 行均保留；queue cancelled 作为终态计数。
- 回归：focused `49 passed`；非 Flet 主体 `234 passed`；非 UI import smoke `19 passed`；维护专项 `10 passed`；compileall PASS；release_check 静态 PASS。
- 当前容器无可安装的 Flet 0.27.6，完整 Windows/Flet/PyInstaller/GUI 门禁待 Codex。
- 正式数据零接触；未执行 Git 写入。状态：NO-GO。

## 2026-08-02 PR1 直接源码候选：Windows 实机验收

- Git 隔离分支从 main@50346f9da9a5d24dda99f7d8c6c21e2f9210c1a6 导入完整候选源码；git diff --check 与 compileall 通过。
- 完整 Windows pytest：294 passed, 3 skipped；focused：49 passed；跳过项均为本机不可用 symbolic link。
- release check、PyInstaller one-folder、EXE 校验通过。四页、批量粘贴取消、工具页冻结与三轮启动/关闭实机通过；托盘彻底退出后无残留。
- 未提交、未推送、未创建 PR 或 Release。高 DPI 视觉复核仍待用户实际显示缩放环境。