# 隔离下载与 Flet UI 验收规范

> 更新：2026-07-20
> 适用条件：正式下载器仍有大量 completed/failed/paused/queued/downloading 混合任务。

## 1. 目标

本规范用于验证下载核心和 Flet UI，而不接触正在运行的正式环境。

所有验收必须使用：

```text
独立仓库副本
独立 Python 虚拟环境
全新的空 sandbox
独立 config.json
独立 history.db
独立 Downloads
```

禁止把 smoke test 指向正式程序目录、正式下载目录或正式 `history.db`。

## 2. 自动化本地端到端测试

本地模拟服务器实现 ASMR.one 兼容的 metadata、tracks、封面和媒体接口，并支持：

- HTTP 200 完整下载；
- HTTP 206 Range 续传；
- HTTP 416 已完整断点确认；
- 1 MiB 固定内容和 SHA-256 验证。

启动服务器：

```bash
python scripts/fake_asmr_server.py --port 8765
```

在另一个终端运行实际 Orchestrator 下载：

```bash
python scripts/live_download_smoke.py \
  --sandbox /tmp/arsm-live-smoke \
  --rj RJ99999999 \
  --mirror http://127.0.0.1:8765 \
  --max-bytes 2097152
```

成功条件：

```text
status = download_ok
最终文件存在
最终大小与 metadata 一致
报告包含 SHA-256
history.smoke.db 只位于 sandbox
```

## 3. Windows 真实 ASMR.one 小样本测试

默认样本：

```text
RJ01575399
```

样本失效、下架或最小文件超过限制时，可以替换为任意公开、体积较小的作品。不要使用正式队列中已经存在的 RJ。

PowerShell：

```powershell
python scripts/live_download_smoke.py `
  --sandbox "D:\ARSM-Smoke\live-download" `
  --rj RJ01575399 `
  --max-bytes 67108864
```

需要代理时只给 smoke sandbox 指定：

```powershell
python scripts/live_download_smoke.py `
  --sandbox "D:\ARSM-Smoke\live-download" `
  --rj RJ01575399 `
  --proxy "http://127.0.0.1:7897" `
  --max-bytes 67108864
```

该脚本不会读取仓库或正式目录中的 `config.json`、`queue.json`、`history.db`。

## 4. Flet UI sandbox

先启动本地模拟服务器，然后启动真实 AppController：

```powershell
python scripts\fake_asmr_server.py --port 8765
```

```powershell
python scripts\run_ui_smoke.py `
  --sandbox "D:\ARSM-Smoke\ui" `
  --rj RJ99999999 `
  --mirror http://127.0.0.1:8765 `
  --view desktop
```

人工检查：

1. 输入框已填入测试 RJ；
2. 添加后只产生一个作品卡片；
3. 准备中、排队、下载中、完成状态顺序合理；
4. 进度、大小和速度不出现负数或回退；
5. 暂停保留 `.part`，恢复后不重复写入；
6. 重连按“暂停完成后再恢复”的顺序执行；
7. 强制重复下载只在明确点击后生效；
8. 打开目录使用数据库中的 canonical path；
9. 批量暂停/恢复不会卡死窗口；
10. 失败信息可见，不把失败显示为完成。

## 5. 当前自动化覆盖

portable tests 已覆盖：

- 200 完整下载；
- 206 正确 Range；
- 416 仅在本地文件大小精确匹配时完成；
- Range 不匹配时从零重试而不拼接损坏内容；
- 取消和最终失败记录真实 `.part` 大小；
- 过期 metadata cache 可用于恢复暂停任务；
- 嵌套音轨在 UI 详情中递归显示；
- 镜像故障切换；
- 设置页写入真实 work/file concurrency；
- UI 控制通过后台 loop 和 UI queue 分离。

## 6. 尚需 Windows 验收

当前 Linux 容器无法完成以下结论：

- 真实 ASMR.one 网络下载；
- Windows Flet 桌面视觉和交互；
- Windows 文件锁、长路径、杀毒软件拦截；
- 正式代理环境下的镜像和音频下载。

这些项目只能由 Codex 在独立 Windows sandbox 验收，不能在正式 100+ 任务目录中执行。
