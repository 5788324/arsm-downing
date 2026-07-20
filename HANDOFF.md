# ARSM Suite 交接说明

## 当前版本

```text
0.9.0-rc.1
分支：chatgpt/takeover-20260718
```

## 当前事实

- 代码级接手、下载核心、资源库、迁移、External Intake 沙盒、Tools 维护和发布候选收口已完成。
- portable tests：204 项。
- 用户正式环境仍有 100+ completed/failed/paused/queued/downloading 混合任务。
- 正式 `history.db`、下载目录和队列从未在开发环境中修改。
- 真实目录迁移、External Intake execute 和 backlog 批量恢复仍等待维护窗口。

## 下一位 AI/Codex 必做

1. 从最新 Bundle/GitHub 分支创建全新 Windows checkout。
2. 运行 `python scripts/release_check.py`。
3. 运行 `.\scripts\build_windows.ps1`。
4. 在全新目录解压 ZIP，不覆盖当前运行程序。
5. 运行 `scripts/run_windows_acceptance.ps1`，生成证据目录。
6. 使用小作品完成真实 ASMR.one 下载。
7. 检查启动、关闭、暂停、恢复、打开目录、资源库搜索和 Tools 只读操作。
8. 提交截图、日志、snapshot manifest、下载 SHA-256 和 UI 观察表。

## 禁止直接执行

```text
python tools/external_intake.py --execute --confirm-bulk
正式资源库批量迁移
正式数据库 VACUUM
正式 backlog execute
覆盖当前仍在下载的程序目录
```

## 最终发布门槛

- GitHub Linux/Windows CI 通过。
- Windows release artifact 构建通过。
- Windows/Codex 真实下载与 UI 验收通过。
- 当前 100+ 混合任务自然清空或进入明确维护窗口。
- 再决定是否开放 T7 小批量目录整理。
