# TAKEOVER-T9 发布候选收口

## 版本

```text
ARSM Suite 0.9.0-rc.1
```

## 本阶段完成

- 统一应用版本、窗口标题和 Windows 版本资源。
- 源码与冻结便携版使用稳定应用目录，不再受快捷方式工作目录影响。
- `config.json` 使用临时文件、flush、fsync 和原子替换保存。
- 关闭流程改为幂等：暂停任务、等待取消、停止 workers、关闭 HTTP、提交并关闭 SQLite、停止事件循环。
- 音频标签扩展至 MP3、FLAC、Vorbis OGG、Opus、M4A/M4B/MP4、WAV、AIFF、WMA/ASF。
- 封面 MIME 依据文件签名识别，不再固定写成 JPEG。
- OGG/Opus 使用 `metadata_block_picture`；MP4 支持 JPEG/PNG cover。
- 删除含本机临时路径的旧 PyInstaller spec，建立可复现 one-folder 构建。
- 增加 Windows 构建脚本、release workflow、版本资源和发布检查。
- 新增 portable 回归，统一门达到 204 项。

## 已验证

```text
python -W error::ResourceWarning -m pytest -q：204 passed
python -m compileall：PASS
pip check：PASS
Linux PyInstaller Analysis/PYZ/EXE/COLLECT：PASS
release_check --skip-tests：PASS
```

## 尚需 Windows 证据

- Windows one-folder EXE 启动和关闭。
- Flet Desktop 视觉、按钮和状态文案。
- 真实 ASMR.one 小作品下载。
- Windows 文件锁、长路径和杀毒软件影响。
- GitHub Windows release workflow artifact。

这些事项不阻塞代码进入 Release Candidate，但阻塞正式稳定版标签。
