# ARSM Suite 构建与发布

当前发布候选版本：`0.9.0-rc.1`。

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
release/ARSM-Suite-0.9.0-rc.1-windows-x64.zip
release/ARSM-Suite-0.9.0-rc.1-windows-x64.zip.sha256
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

Linux 已完成 PyInstaller Analysis、EXE 和 COLLECT 构建验证。Windows EXE 启动、Flet Desktop 运行时、真实站点下载、文件锁和长路径仍以 Windows/Codex 证据为最终结论。
