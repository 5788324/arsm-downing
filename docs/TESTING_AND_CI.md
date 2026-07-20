# 测试与 CI 规范

## 默认命令

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

默认测试门必须只使用临时目录和临时 SQLite。pytest 只从 `tests/`
收集测试，并默认排除：

- `manual`
- `windows_integration`
- `live_network`

## 运行中下载器保护

下载器仍在工作时，不得升级其依赖、替换程序、运行迁移工具，也不得在
生产程序的工作目录中运行测试。

pytest 启动时若在仓库根目录发现以下任一实时状态文件，会直接退出：

- `history.db`
- `config.json`
- `queue.json`

开发测试必须使用干净克隆。需要检查仍在持续写入的数据库时，先创建一致性
只读快照：

```powershell
python scripts/create_db_snapshot.py `
  --source "E:\path\to\active\history.db" `
  --output "D:\arsm-test-snapshots\history-20260720.snapshot.db"
```

创建后再统计混合任务状态：

```powershell
python scripts/inspect_db_snapshot.py `
  --snapshot "D:\arsm-test-snapshots\history-20260720.snapshot.db"
```

检查命令只读取快照，并且必须先验证相邻 manifest。

快照工具具备以下约束：

- 使用 SQLite `mode=ro` 打开源数据库；
- 使用 SQLite online backup API；
- 不手工复制或修改 `history.db-wal` / `history.db-shm`；
- 对快照执行 `PRAGMA integrity_check`；
- 在快照旁生成文件大小和 SHA-256 manifest；
- 目标已存在时拒绝覆盖；
- manifest 安装失败时删除未验证的孤立快照。

快照仍属于用户私有数据，只能保存在本地验收目录。

## 测试分类

### Portable

在 Linux 和 Windows CI 中执行。不得使用真实用户数据、外部网络、GUI 手工
交互或固定本机路径。

### Manual

需要明确的人工操作、参数、凭据或结果观察。类似
`scripts/test_core_download.py` 的历史脚本仍属于 manual，不进入默认测试门。

### Windows integration

依赖 Windows 桌面、Flet runtime、Windows 文件锁、长路径或复制资源库沙盒。
只交给 Codex 执行，不得面向活跃资源库运行。

## CI

`.github/workflows/ci.yml` 定义一个精简 portable workflow：

- Ubuntu + Python 3.10；
- Windows + Python 3.12。

流程安装精确锁定的兼容依赖，编译 Python 源码，检查 Flet UI 模块导入，最后
运行 portable pytest。workflow 带路径过滤，纯文档修改不会触发 CI。

## 依赖策略

`requirements.txt` 精确锁定当前 runtime 兼容集。Flet 固定为 `0.27.6`，原因是
现有 UI 大量使用 legacy `ft.icons` 和 `ft.colors` API。升级到新 Flet 架构属于
独立 UI 迁移任务，不作为常规依赖升级处理。

`requirements-dev.txt` 额外加入 pytest。修改任一锁定版本前必须完成：

1. 新建干净虚拟环境；
2. UI/core 模块导入 smoke test；
3. portable pytest；
4. Windows/Flet 验收；
5. 确认后才能替换用户现有安装环境。

## 下载和 UI Smoke

下载核心的本地真实 HTTP 测试、ASMR.one 兼容服务器和 Windows 隔离 UI 流程见：

```text
docs/LIVE_DOWNLOAD_AND_UI_SMOKE.md
```

这些测试不得在正式程序目录或正式 100+ 任务环境中运行。
