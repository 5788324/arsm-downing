# Codex Windows 实机验收：ARSM Suite 0.9.0-rc.1

> 状态：待完成  
> 验收对象：正式 GitHub Pre-release  
> 禁止修改代码、`main`、标签、正式数据库和正式下载任务。

## 1. 基线

```text
仓库：https://github.com/5788324/arsm-downing
Release：https://github.com/5788324/arsm-downing/releases/tag/v0.9.0-rc.1
main：9f292e7947804f2e4d53290039501f79c6d1805d
标签：v0.9.0-rc.1
ZIP：ARSM-Suite-0.9.0-rc.1-windows-x64.zip
SHA-256：fe00bb9d47a6b16949573b57a2c483f1121e3a8b3fec0777d101ae82e15747c2
```

本地唯一仓库：

```text
G:\Antigravity\arsm.one\arsm-downing
```

## 2. 隔离目录

创建：

```text
G:\Antigravity\arsm.one\ARSM-Codex-Acceptance-0.9.0-rc.1\
├─ Release\
├─ App\
├─ Downloads\
└─ Evidence\
```

禁止复制或读取：

```text
正式 history.db
正式 config.json
正式 queue.json
*.db-wal
*.db-shm
E:\arsm
现有正式程序目录
现有 100+ 下载任务
```

## 3. 下载和校验 Release

```powershell
gh release download v0.9.0-rc.1 `
  --repo 5788324/arsm-downing `
  --dir "G:\Antigravity\arsm.one\ARSM-Codex-Acceptance-0.9.0-rc.1\Release" `
  --pattern "ARSM-Suite-0.9.0-rc.1-windows-x64.zip" `
  --pattern "ARSM-Suite-0.9.0-rc.1-windows-x64.zip.sha256"

Get-FileHash `
  "G:\Antigravity\arsm.one\ARSM-Codex-Acceptance-0.9.0-rc.1\Release\ARSM-Suite-0.9.0-rc.1-windows-x64.zip" `
  -Algorithm SHA256
```

必须确认：

- 实际 SHA-256 等于预期值；
- `.sha256` 文件一致；
- ZIP 可以完整解压；
- ZIP 非空；
- ZIP 内存在 `ARSM-Suite.exe`；
- 记录 ZIP 大小和条目数。

解压到 `App`。

## 4. 三次启动和关闭

每轮：

1. 从 `App` 目录启动 `ARSM-Suite.exe`；
2. 等待主窗口完整显示；
3. 检查无控制台错误、黑屏或启动即退出；
4. 正常关闭；
5. 执行：

```powershell
Get-Process ARSM-Suite -ErrorAction SilentlyContinue
```

关闭后不应残留进程。

连续完成三次。

## 5. UI 页面

保存截图：

```text
01-dashboard.png
02-download-center.png
03-library.png
04-tools.png
05-settings.png
```

检查：

- 中文无乱码；
- 控件无严重重叠或裁切；
- 最大化、还原、最小化正常；
- 下载中心、资源库、统计、工具和设置可切换；
- 空数据库页面不崩溃；
- 不显示硬编码用户路径或假 RJ；
- 搜索不存在 RJ 不崩溃；
- 打开目录失败时有明确提示。

## 6. 设置持久化

将输出目录设置为：

```text
G:\Antigravity\arsm.one\ARSM-Codex-Acceptance-0.9.0-rc.1\Downloads
```

关闭并重启，确认仍然生效。

记录 `config.json`、`history.db`、`queue.json` 实际生成路径。它们只能位于本次隔离目录。

## 7. 真实 ASMR.one 小样本

选择合法可访问、体积较小的作品。

检查：

1. 元数据和文件列表；
2. 封面；
3. 开始下载；
4. `.part` 非空；
5. 点击暂停；
6. `.part` 保留；
7. 关闭并重启；
8. 继续下载；
9. 从断点继续；
10. 完成后最终文件存在；
11. 无无效 `.part`；
12. 隔离 `history.db` 只包含本次任务；
13. 正式环境无变化。

找不到小作品时，可以只完成开始、暂停、重启和恢复，结论使用 `PASS_WITH_NOTES`，不得伪造完成。

真实站点不可访问时保存 DNS、HTTP、代理和应用日志。

## 8. Tools 限制

允许只读：

- 系统诊断；
- 网络诊断；
- 队列预览；
- 缓存预览；
- External Intake dry-run；
- Migration dry-run。

禁止：

- External Intake Execute；
- 正式迁移；
- VACUUM；
- backlog execute；
- 目录整理；
- 正式数据库写入维护。

## 9. 报告

生成：

```text
Evidence\CODEX_WINDOWS_ACCEPTANCE.md
```

至少包含：

- Windows 版本和验收时间；
- main 和标签 SHA；
- Release URL；
- ZIP 大小、条目数和 SHA-256；
- 三次启动/关闭；
- 页面检查；
- 设置持久化；
- 真实样本；
- `.part` 大小；
- 暂停、重启和恢复；
- 日志错误摘要；
- 截图列表；
- 是否接触正式环境；
- 最终结论：`PASS`、`PASS_WITH_NOTES` 或 `FAIL`。

## 10. 最终回复模板

```text
Windows：
验收目录：
main SHA：
标签 SHA：
ZIP SHA-256：
三次启动/关闭：
UI：
设置持久化：
真实样本：
暂停：
.part：
重启恢复：
最终文件：
正式环境是否触碰：
Evidence：
结论：
```

失败时只提交证据，不修改代码。
