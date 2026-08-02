# T15 真实网络与认证验收（隔离）

- 日期：2026-08-02
- 结论：**PASS_WITH_NOTES**
- 源码分支：`codex/t15-network-feedback`
- 正式环境：零接触；所有运行数据仅位于 `C:\tmp\arsm-t15-*`。

## 真实 ASMR.one 小作品

- 样本：`RJ01276295`；metadata 与封面分别使用 Clash `http://127.0.0.1:7897`。
- 真实封面：`cover.jpg` 为 75,620 bytes；路由追踪记录 metadata 两次和 cover 一次均使用上述代理。
- 音频：`download_proxy=None`、`download_fallback_to_proxy=false`；两个 MP3 直接向音频主机取得 HTTP 200，恢复时取得 HTTP 206 与正确 `Content-Range`。
- 暂停：`.part` 在任务取消并回收后为 45,540 bytes，2 秒后仍为 45,540 bytes。
- 完成：两个文件共 7,860,019 bytes，最终 SQLite `completed=2`、`active_rows=0`；SHA-256 已写入隔离 JSON。

## 401、断网与恢复

使用本机真实 HTTP socket（独立 SQLite）验证失败和恢复分支，未伪造下载成功：

- 未带 token 时服务返回 401；UI 状态回调为 `Metadata failed (metadata request failed: 401, message='Unauthorized' ...)`，works/downloads 均为 0。
- 配置受控 token 后服务收到 `Authorization: Bearer accepted-token`，任务重新进入 `Prepared`。
- 停止本机服务后，状态明确包含 `Connection timeout`，works/downloads 均为 0；恢复服务后同一准备流程成功。
- 修复：`NetworkKernel` 以 task-local 状态保留最后 metadata 错误，`Orchestrator` 将其带入失败消息，避免此前无条件显示 `empty response`。

## 自动回归与边界

```text
compileall: PASS
pytest: 245 passed, 3 skipped
skipped: Windows 环境无法创建 symbolic link
```

- 未读取、修改或扫描 `E:\arsm`、正式 `history.db`、`config.json`、`queue.json`、正式任务或 `.part`。
- 仍未宣称真实站点主动返回过 401；401/auth 恢复使用本机真实 HTTP 服务器精确验证产品分支。真实站点的 metadata、封面、音频、暂停及 206 续传均已通过。
## T15 候选 one-folder 构建

- 独立构建目录：`C:\tmp\arsm-t15-onefolder-20260802`（不覆盖用户正在运行的 `dist`）。
- ZIP：`ARSM-Suite-0.9.0-rc.2-windows-x64.zip`，64,734,852 bytes，203 个 ZIP 条目，包含 `ARSM-Suite.exe`。
- SHA-256：`bc680bc1d1b95aa6a9f5270901767d936994fe1ee9a7d7483b8d46f7f135a648`，与 `.sha256` 一致。
- EXE FileVersion/ProductVersion：`0.9.0-rc.2`。
- 这是未发布候选构建；既有 GitHub Pre-release 未被替换或修改。
