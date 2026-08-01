# Windows T10 RC2 验收记录（未放行）

日期：2026-08-01
结论：条件 GO（禁止提交、推送、建 PR 或发布）

## 基线

- 隔离 worktree：`G:\Antigravity\arsm.one\arsm-downing-t10-worktree`
- 基线：`main@9f292e7947804f2e4d53290039501f79c6d1805d`
- 分支：`codex/t10-queue-service`
- Flet：`0.27.6`
- 自动测试：`230 passed, 3 skipped`；跳过项仅为当前 Windows 环境不支持符号链接的三项测试。
- `compileall`：通过；`git diff --check`：通过。

## 已通过的隔离 GUI 证据

- RC2 one-folder：`ARSM-Suite-0.9.0-rc.2-windows-x64.zip`，57,247,433 bytes，195 个条目；SHA-256：`a8961e730111519b49200ff7c82f06930fd81d0d30e6aaba19e829c37416fdb3`。
- EXE 文件版本和窗口标题均为 `0.9.0-rc.2`。
- 200 个合成任务的七种筛选均显示与 SQLite 一致的数量：活动 160、下载中 0、等待中 80、暂停 40、失败 40、完成 40、全部 200。
- 从“全部”的第二页切换到“活动任务”后自动回到第 1/7 页；完成任务只在“已完成/全部”筛选中出现。
- 下载中心、资源库、系统工具、设置连续往返两轮，返回下载中心后队列摘要仍与 SQLite 一致；不存在“统计与成就”页。
- 设置页将 `metadata_concurrency` 从 2 保存为 3；正常关闭、重启后界面和隔离 `config.json` 仍为 3；随后恢复默认值 2。
- 三轮标题栏正常关闭均无 `ARSM-Suite` 残留进程。
- 新的最小隔离实例通过本机 `127.0.0.1` 限速 HTTP 服务下载真实字节流：下载中显示作品/总网速与 ETA；暂停后 `.part` 为 20,578,304 bytes 且稳定；全部继续发出 `Range: bytes=20578304-`，收到匹配的 HTTP 206；最终 `local-t10.bin` 为 32,311,682 bytes，`.part` 消失，SQLite 记录 registered/completed，活动队列立即移除该作品。

截图和关闭证据：`Evidence/T10-RC2/`。

## 未完成的放行项

- 批量 RJ 预览的取消/确认：桌面自动化可点击并显示控件焦点，但未能稳定将文本输入或文件选择事件送达隔离 Flet shell；不能将单元测试替代为现场证据。
- 真实小任务的开始、非空 `.part`、全部暂停、全部继续、Range 恢复和最终文件：通过，使用本机限速 HTTP 流和独立 SQLite；未访问网络或正式下载环境。

因此本轮不进行 Git 提交、push、PR，也不发布。正式 `history.db`、`config.json`、`queue.json`、现有下载任务、`.part` 和 `E:\arsm` 均未访问或修改。


## 2026-08-01 后续复测

- 已完成本机 HTTP 真字节流的完整链路：下载、网速/ETA、暂停、非空且稳定的 .part、Range bytes=20578304- 与 HTTP 206、最终文件 32,311,682 bytes、SQLite completed/registered、活动队列移除。
- 发现并修复 FilePicker 未注册到 page.overlay 的 Flet 0.27.6 兼容问题，新增回归测试；修复后全量测试为 231 passed、3 skipped。
- 重新构建的候选 ZIP：57,246,973 bytes，195 项，SHA-256 912d7b819613ce56f5182718655605f112b5ef6af31460eae72b4a86e66f0d51。
- 但实际新构建 EXE 点击批量导入文件后仍不弹出 Windows 选档框，日志无结果回调。因此批量预览取消/确认的现场证据仍失败；维持条件 GO，禁止 Git 放行。


## 2026-08-01 GPT 批量粘贴修复（待 Windows 复测）

原生 FilePicker 不再作为 RC2 批量输入入口。当前修复将按钮改为“批量粘贴”，在应用内部打开多行 TextField 对话框。

代码级结果：

- 输入对话框取消：不调用预览、不写 DB、不创建目录、不启动下载；
- 预览对话框取消：works/downloads/队列/目录保持不变；
- 最终确认：只提交 `BatchEnqueuePreview.ready`；
- 重开输入框：旧的未提交文本不会保留；
- FilePicker 从 `page.overlay` 移除，最终验收不再依赖原生 Windows 选档框；
- 临时 Flet 接口桩下全量测试：238/238 PASS。

仍需在真实 Flet 0.27.6 最终 EXE 中确认：

1. “批量粘贴”按钮可稳定打开多行输入框；
2. 混合输入预览显示 8 类统计；
3. 取消前后 works/downloads/活动队列/目录树零变化；
4. 确认后实际新增数等于 ready 数，其他分类不入队。

上述四项通过前，整体结论继续为条件 GO，禁止提交、push、PR 和发布。


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