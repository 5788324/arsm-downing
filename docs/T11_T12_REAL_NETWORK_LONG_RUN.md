# T11/T12 真实网络与长期运行验收（隔离）

- 时间：2026-08-01
- 结论：**PASS_WITH_NOTES**
- 工作树：`arsm-downing-t10-worktree` / `codex/t10-queue-service`
- 样本：`RJ01276295`
- 隔离目录：`G:\Antigravity\arsm.one\ARSM-T11-T12-Acceptance-20260801-audio`

## 已通过

- metadata 与封面通过 `http://127.0.0.1:7897`；音频通道配置 `download_proxy=None`。
- 真实 Orchestrator 从 89 个文件中按 audio、最小优先选择 4 个，合计 `30,285,707` bytes。
- 暂停时四项数据库状态为 `paused`；观测到非空 `.part=54,694` bytes，2 秒后大小未变化。
- 服务 shutdown、重新创建服务后，两条恢复请求分别从 `54694` 和 `53259` bytes 发起，均收到 HTTP `206` 与匹配的 `Content-Range`。
- 4/4 音频最终大小匹配 metadata，SHA-256 已写入 `t11-t12-live-acceptance.json`；最终 SQLite 为 `completed=4`、`ignored=56`、活动任务 `0`。
- 连续运行 `2,741.38` 秒（45 分 41 秒），27 个一分钟快照无任务丢失、无重复写入或服务退出；正常 shutdown 完成，未发现本验收 Python 或 ARSM-Suite 残留进程。

## 备注与边界

- 早期字幕/文本文件选择试跑已中止并保留独立日志；不计入本报告。最终音频 sandbox 独立于该试跑。
- 本轮未在可见 Flet 窗口中重复四页往返；下载中心、资源库、系统工具和设置的可见 UI 往返继续以 T10 Windows 验收记录为准。
- Defender 拦截、长路径失败和文件占用均未触发，不能表述为通过。
- 正式 `history.db`、`config.json`、`queue.json`、`E:\arsm`、正式任务与 `.part` 均零接触。隔离产物按约定暂时保留。
- 本报告不放行 Git、PR 或 Release；仍需复核最终代码、文档与 CI 后再单独决定。
## 最终自动回归（2026-08-01）

- 在新建的无运行数据源码副本中，固定可写 TEMP 后执行：`236 passed, 3 skipped in 95.43s`。
- 3 个 skipped 均为 Windows 环境无法创建 symbolic link；`compileall` 与真实 Flet 导入通过。
- 当前工作树旁的 pytest 保护门拒绝执行，是因为隔离验收运行已生成本地 `history.db/config.json`；该拒绝是预期安全机制，不是测试失败。
- 新增验收脚本不被冻结应用导入，未改变下载器生产模块或 Windows one-folder 包内容，因此本轮不重复构建 ZIP；既有 RC2 Fix2 构建仍仅作为上一轮二进制证据，未因此放行发布。
## 2026-08-02 T15 真实网络与认证验收

- `RJ01276295` 在全新 `C:\tmp` sandbox 通过真实 metadata/封面代理、音频直连、暂停稳定、HTTP 206 续传和两文件完整校验；详情见 `docs/T15_NETWORK_AUTH_ACCEPTANCE.md`。
- 修复 metadata 失败原因被降级为 `empty response`：401 和断网现在会把具体 HTTP/连接错误传到下载器状态；受控真实 HTTP 401、断网和恢复均已验证，失败时 SQLite 零新增。
- 最终自动回归：`245 passed, 3 skipped`；3 项 skipped 是当前 Windows 无法创建 symbolic link。
- 正式 `E:\arsm`、history/config/queue、正式任务与 `.part` 全程零接触；本轮未创建标签或发布。
