# CODEX Windows Acceptance — ARSM Suite 0.9.0-rc.1

- 验收时间：2026-07-22 至 2026-07-23
- Windows：Windows 11 Pro 10.0.26200 x64
- main SHA：9f292e7947804f2e4d53290039501f79c6d1805d
- 标签 SHA：9f292e7947804f2e4d53290039501f79c6d1805d
- Release：https://github.com/5788324/arsm-downing/releases/tag/v0.9.0-rc.1
- 验收目录：G:\Antigravity\arsm.one\ARSM-Codex-Acceptance-0.9.0-rc.1

## Release 校验

- ZIP：Release\ARSM-Suite-0.9.0-rc.1-windows-x64-2.zip
- 大小：57,685,550 字节；条目：204；ZIP 非空。
- SHA-256：`fe00bb9d47a6b16949573b57a2c483f1121e3a8b3fec0777d101ae82e15747c2`。
- 实际摘要、`.sha256` 文件和 GitHub Release 摘要一致；包内含 `ARSM-Suite.exe`，且无绝对路径或 `..` 路径穿越条目。

## EXE、窗口与页面

- 先前“自动化启动失败”已由用户提供的正式 EXE 主窗口截图和后续直接窗口连接推翻；该记录不再作为失败依据。
- 连续 3 次启动均成功显示 `ARSM Suite 0.9.0-rc.1` 主窗口。
- 每次点击标题栏关闭均正常退出；关闭后无 ARSM 主窗口残留。
- 下载中心、资源库、统计与成就、系统工具、设置页均成功打开，截图见 Evidence。
- 新的隔离配置已原子保存并在重启后保留。默认输出目录实际为 `App\Downloads`，仍完全位于独立验收目录；这与计划中的根级 `Downloads` 不同，记为备注。
- 全新隔离数据库中资源库、下载队列与统计均为 0，属于预期空数据状态。

## 真实 ASMR.one 下载、暂停与恢复

- 用户在隔离应用中提交 10 个任务；SQLite 持久化了 9 个不同 RJ。第 10 个没有形成独立 work，原因未在本轮修改或推断。
- 元数据和文件列表成功写入：下载表共 475 条，其中恢复前有 48 条 downloading、418 条 queued、9 条 completed。
- 磁盘观察到非空 `.part`；暂停后为 4 个 `.part`、合计 30,285,312 字节，且数据库变为 466 paused，断点没有被删除。
- 正常关闭、重启后，9 个任务均显示已暂停，数据库状态保持 466 paused。
- 点击“全部开始”后恢复为 93 downloading、370 queued、12 completed；`.part` 从 4 个增长至 8 个，总量从约 30.3 MB 增至 53,975,872 字节。
- 已确认非空最终 MP3 文件存在，例如 `Track1...mp3` 为 14,017,924 字节；因此不只是创建空目录或空包。
- 当前隔离配置没有下载代理（`download_proxy = null`），本次真实音频下载按默认直连策略运行。

## 已知 UI 备注

- 下载中心的卡片进度会更新，例如已有卡片显示 36%/31%/59%、0.4 MB/s 与 ETA。
- 底部汇总文本在恢复后仍显示“下载中 0、排队 0、暂停 9”，与 SQLite 的 `93 downloading + 370 queued` 不一致，确认为刷新/汇总显示缺陷。

## 隔离与正式环境

- 未读取或修改 `E:\arsm`、正式程序目录、正式 `history.db`、`config.json`、`queue.json` 或现有下载任务。
- 未执行 External Intake Execute、正式迁移、VACUUM、backlog execute 或目录整理。
- 未修改业务代码、工作流、文档或 main 分支。

## 最终结论

PASS_WITH_NOTES — Release、桌面 EXE 启动/三次关闭、页面、隔离设置持久化、真实元数据与文件列表、非空 `.part`、暂停、关闭重启、恢复和最终文件均已验证通过。发布前应修复下载中心底部汇总与真实任务状态不同步的问题，并调查“提交 10 个仅持久化 9 个不同 RJ”的原因。
