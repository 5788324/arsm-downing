# TAKEOVER-T10 Queue Service 验收说明

## 范围

T10 解决 100+ 任务时的 SQLite N+1、批量输入不可解释、元数据并发无独立上限和隐藏页面无意义刷新问题。Windows 验收后，批量输入主入口进一步从不可靠的原生 FilePicker 改为应用内“批量粘贴”多行对话框。

## 实现

### DownloadService

- 复用 AppController 的唯一 `LibraryVault`；
- 一次聚合 CTE + 一次字节汇总，总计固定两次 SELECT；
- 输出不可变 page/item/summary；
- 保留 orphan downloads；
- terminal work 不被历史 paused/failed 行重新激活；
- read-only，不修改 DB。

### Batch preview

输入：RJ、纯数字、ASMR.one URL、空格/换行/中英文标点。

分类：

```text
ready
invalid_tokens
duplicate_input
already_active
already_in_queue
already_in_library
already_completed
needs_review
```

预览不写 DB、不建目录、不发网络请求。

### MetadataScheduler

- asyncio FIFO queue；
- 默认 2，最大 8；
- 作品 metadata 和 tracks 在同一 slot 内完成；
- 外部作品补全也复用同一队列；
- 与音频 work/file workers 独立；
- shutdown 幂等。

### Lifecycle

- 下载页隐藏：停止卡片重绘；
- 返回：重新获取快照；
- 资源库隐藏：使旧 worker 回调失效；
- Tools/Settings：激活时刷新。

## 自动证据

```text
pytest 232/232 PASS
compileall PASS
任务量 10/50/100/200：每次 2 SELECT
metadata 100 作业：peak_active=2
```

## Codex Windows 验收

必须使用临时 DB 和隔离目录。至少构造 200 个任务、每个 3 个文件，验证：

1. 页面首次打开不冻结；
2. 活动/下载中/等待/暂停/失败/完成/全部筛选；
3. 上一页/下一页；
4. 全部暂停/继续后汇总同步；
5. 完成项从活动筛选消失；
6. 总网速与作品网速同时正确；
7. 批量输入取消前零新增任务；
8. 确认后只添加 ready；
9. metadata_concurrency 保存重启；
10. 四页切换和正常关闭。

## 明确不测

不得使用正式 DB、正式 E 盘资源库或现有 100+ 下载任务作为夹具。


## 2026-08-01 批量粘贴补充

- “批量导入文件”从 RC2 主界面移除；
- FilePicker 不再注册到 `page.overlay`；
- “批量粘贴”直接打开应用内 multiline TextField；
- 输入取消和预览取消均为零副作用；
- 最终确认只提交 `ready`；
- 真实 Flet 最终 EXE 验收仍是 Git 放行前最后一项。


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