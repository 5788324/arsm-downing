# ARSM Suite 构建与发布

当前正式候选版本：`1.0.0`。

## Windows 产物

```powershell
.\scripts\build_windows.ps1
.\scripts\build_installer.ps1
```

输出：

```text
release/ARSM-Suite-1.0.0-windows-x64.zip
release/ARSM-Suite-1.0.0-windows-x64.zip.sha256
release/ARSM-Suite-1.0.0-setup.exe
release/ARSM-Suite-1.0.0-setup.exe.sha256
```

安装版使用固定 AppId，后续安装器会原地升级；程序文件在 `%LOCALAPPDATA%\Programs\ARSM Suite`，用户数据在 `%LOCALAPPDATA%\ARSM Suite`，卸载默认保留数据。

## 发布门禁

1. `python scripts/release_check.py`
2. 全量 `pytest`
3. 校验 ZIP/安装器/两个 SHA-256 文件
4. 隔离安装、启动、安全退出、卸载和数据保留
5. 合并 PR 后创建 `v1.0.0` 标签，等待 Release workflow
6. 核验 Artifact 后创建正式 GitHub Release 并上传四个文件
