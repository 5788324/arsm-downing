# ARSM Suite 1.0.0 发布与安装说明

## Windows 安装版

发行包同时包含两种 Windows x64 文件：

- `ARSM-Suite-1.0.0-setup.exe`：推荐。运行安装器后会在 Windows「已安装的应用」中显示 ARSM Suite，可从开始菜单或卸载入口管理。
- `ARSM-Suite-1.0.0-windows-x64.zip`：免安装便携版。解压到可写目录后运行 `ARSM-Suite.exe`。

安装器使用固定 AppId，之后运行更高版本的安装器会进行原地升级，而不是创建第二个 ARSM Suite。

## 用户数据与卸载

安装版程序文件位于 `%LOCALAPPDATA%\Programs\ARSM Suite`（或用户选择的位置）。可变数据位于：

```text
%LOCALAPPDATA%\ARSM Suite\
  config.json
  history.db
  Downloads\
  logs\
```

因此更新安装器不会覆盖下载、SQLite 历史或设置。卸载默认只移除程序和快捷方式，保留用户数据，防止误删仍在下载的作品；如需彻底清除，请先在程序中停止任务，再手动删除上面的用户数据目录。

便携版保持原有行为：数据与 EXE 同目录保存。不要将便携版解压到只读目录，也不要在运行或下载中覆盖其文件。

## 发布流程

1. 在干净 Windows x64 环境运行 `scripts/release_check.py`、全量 pytest 与 `scripts/build_installer.ps1`。
2. 校验 ZIP、安装器和两个 `.sha256` 文件；安装器应包含卸载入口。
3. 用安装器在空白目录安装、启动、关闭、覆盖升级并卸载；确认 `%LOCALAPPDATA%\ARSM Suite` 数据保留。
4. 创建与 `core/version.py` 完全一致的 Git tag，例如 `v1.0.0`，触发 Windows workflow。
5. 验证 GitHub Artifact 后创建正式 GitHub Release，并上传 ZIP、安装器及各自 SHA-256。

当前发布豁免：用户授权跳过 125% / 150% / 200% DPI 的人工视觉验收；该项应在后续维护版本补测。