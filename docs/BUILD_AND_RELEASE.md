# ARSM Suite 构建与发布

当前发布候选版本：`0.9.0-rc.2`（尚未放行发布）。

## Windows 便携版

推荐在 Windows 10/11、Python 3.12 环境执行：

```powershell
.\scripts\build_windows.ps1
```

脚本会：

1. 创建独立 `.venv-build`；
2. 安装 `requirements-build.txt`；
3. 运行 portable pytest；
4. 使用 `ARSMSuite.spec` 构建 one-folder 便携版；
5. 输出 ZIP 和 SHA-256。

产物：

```text
release/ARSM-Suite-0.9.0-rc.2-windows-x64.zip
release/ARSM-Suite-0.9.0-rc.2-windows-x64.zip.sha256
```

## 运行数据位置

源码运行时，应用继续使用当前工作目录。

冻结后的便携版使用 `ARSM-Suite.exe` 所在目录保存：

```text
config.json
history.db
queue.json（仅兼容，不作为真源）
Downloads/
logs/
```

因此不要把程序放在只读目录。建议解压到：

```text
D:\Apps\ARSM-Suite\
```

不要覆盖正在运行且仍有下载任务的旧程序目录。首次验收应解压到全新目录。

## GitHub Actions

- `.github/workflows/ci.yml`：Linux/Windows portable tests。
- `.github/workflows/release-build.yml`：手动或 tag 构建 Windows ZIP。

Windows Runner 构建成功后，下载 `ARSM-Suite-Windows` artifact，并在独立 sandbox 完成真实 ASMR.one 与 Flet Desktop 验收。

## 发布前检查

```powershell
python scripts/release_check.py
```

检查内容：

- 仓库根目录不存在 `history.db/config.json/queue.json`；
- 版本文件和 PyInstaller spec 存在；
- portable pytest 全部通过。

## 当前边界

Linux 已完成 PyInstaller Analysis、EXE 和 COLLECT 构建验证。Windows EXE 启动、Flet Desktop 运行时和真实小文件下载已有隔离证据；文件锁、长路径与 Defender 仍须在触发时记录，不能以未触发表述为通过。

## 2026-08-02 RC2 最终关闭与可见 GUI 验收

- 修复 Flet 0.27.6 窗口生命周期兼容性：关闭事件、阻止默认关闭、销毁窗口均改用 `page.window` API。旧 API 会让原生窗口先消失而保留 Python/下载器进程。
- 无运行数据的隔离源码副本已完成真实 Flet 回归：`237 passed, 3 skipped`；3 个 skipped 均为 Windows 环境不支持符号链接。`compileall`、Flet import 与 `git diff --check` 通过。
- 最终 one-folder：`ARSM-Suite-0.9.0-rc.2-windows-x64.zip`，57,251,928 bytes、195 entries，SHA-256 `37bece06a014631c8756a41de237a6d77db7de7f0f50949257550bdb65ee8e08`；SHA 文件一致，ZIP 内含 `ARSM-Suite.exe`，EXE File/ProductVersion 均为 `0.9.0-rc.2`。
- 最终 EXE 的下载中心、资源库、系统工具、设置四页已可见往返并保存隔离截图；标题栏关闭连续 3 次均记录完整 shutdown，ARSM-Suite 与 Flet 子进程均为零残留。
- 正式 `history.db`、`config.json`、`queue.json`、`E:\arsm`、正式任务与 `.part`：零接触。本地验收通过，下一门槛仅为 Git 提交、PR 与远端 CI；尚未创建 Release。
## 2026-08-02 RC2 正式预发布收口

- PR #10 已合并：`main@8c4215ac5d5a80c0d62c683adcc40cd7f04e216d`；T13 资源库详情和 T14 托盘生命周期已进入主线。
- 正式标签：`v0.9.0-rc.2`，解引用提交精确为上述 main SHA。
- GitHub `windows-release-candidate` 构建通过：`https://github.com/5788324/arsm-downing/actions/runs/30712870981`。
- 正式 Artifact/Pre-release ZIP：`ARSM-Suite-0.9.0-rc.2-windows-x64.zip`，65,206,571 bytes、212 项、SHA-256 `5a6179098faf4e44ca410e87b518c71a418ee7ae09227e236af05e7c51494061`；校验文件一致并含 `ARSM-Suite.exe`。
- Release：`https://github.com/5788324/arsm-downing/releases/tag/v0.9.0-rc.2`（Pre-release）。
- 正式 `E:\arsm`、正式数据库、队列、下载任务与 `.part`：全流程零接触。