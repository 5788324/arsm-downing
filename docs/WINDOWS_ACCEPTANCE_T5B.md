# T5B Windows 隔离验收

> 目标：验证真实 ASMR.one 小样本、Flet Desktop UI 和活跃数据库只读快照。
> 禁止：在正式程序目录安装依赖、运行测试、修改 `history.db` 或操作现有 100+ 队列。

## 一键入口

在干净 checkout 中打开 PowerShell：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\run_windows_acceptance.ps1 `
  -EvidenceDir "D:\ARSM-Acceptance-20260720" `
  -ActiveDb "<正式程序目录>\history.db" `
  -Rj "RJ01575399" `
  -LaunchUi
```

脚本会在 `EvidenceDir` 内创建独立虚拟环境和 `evidence` 目录。正式程序可继续运行。

## 自动阶段

1. 安装 `requirements-dev.txt` 到独立虚拟环境。
2. 在干净仓库运行 portable pytest。
3. 对 `ActiveDb` 使用 SQLite online backup，生成只读快照、manifest 和状态统计。
4. 在全新 `live-download` sandbox 下载一个受大小上限保护的小样本。
5. 启动本地 fake ASMR server 和真实 Flet Desktop UI。
6. UI 关闭后统计 sandbox 中的数据库、队列和下载文件 SHA-256。

## UI 观察范围

只操作 `RJ99999999` 本地模拟作品：

- 添加与排队
- 下载进度
- 暂停与恢复
- 重连
- 完成
- 暂停并隐藏
- 打开目录
- 错误状态文案
- 窗口缩放、按钮遮挡和文字截断

不要在 smoke UI 中配置正式下载目录或正式数据库。

## 证据文件

```text
windows-acceptance-report.json
ui-observation.json
logs/*.stdout.log
logs/*.stderr.log
snapshot/history.snapshot.db
snapshot/history.snapshot.db.manifest.json
live-download/live-smoke-report.json
ui-smoke/history.db
ui-smoke/Downloads/
```

`ui-observation.json` 由 Codex 根据截图和实际点击填写。自动报告中的
`active_database_was_modified` 固定为 `false`。

## 判定

### PASS

- portable tests 通过；
- snapshot `integrity_check=ok` 且 manifest 验证通过；
- live 下载最终大小与 metadata 一致；
- UI 状态、数据库和文件结果一致；
- 正式任务数量和状态未被验收流程改变。

### STOP

出现以下任一情况立即停止：

- EvidenceDir 非空或包含正式状态文件；
- snapshot/manifest 失败；
- live 样本超过 `MaxBytes`；
- UI 指向正式路径；
- 正式数据库或现有队列发生变化；
- UI 卡死、错误状态误报完成或文件大小不一致。
