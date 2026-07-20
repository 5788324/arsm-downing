# Windows 只读验收流程

## 当前现场条件

用户的正式下载器可以继续运行，目前有 100 多个任务，状态混合包含：

```text
completed
failed
paused
queued
downloading
以及可能存在的历史状态字符串
```

这种状态允许进行只读观察，但会阻止所有真实迁移、external intake 执行、清理、
VACUUM、依赖替换和正式目录实验。

## 禁止事项

Codex 不得：

- 暂停、恢复、重试、删除或重新排序正式任务；
- 在运行中程序使用的 Python 环境安装新依赖；
- 在生产程序工作目录运行 pytest；
- 把 `history.db`、`history.db-wal`、`history.db-shm` 当作三个普通文件直接复制；
- 执行 `VACUUM`、WAL checkpoint、repair、migration、cleanup 或 external intake；
- 通过可写连接打开活跃数据库；
- 移动、改名、隔离或全量哈希正式媒体库。

## 第一步：使用干净仓库副本

使用独立的干净 checkout 或解包后的 Bundle。该目录中不得包含：

```text
history.db
config.json
queue.json
```

执行：

```powershell
python -m pip install -r requirements-dev.txt
python -m compileall -q core ui tools tests scripts main.py
python -m pytest  # 当前应为 125 passed
```

正式程序环境保持不变。

## 第二步：创建在线 SQLite 快照

下载器保持运行，在独立测试目录创建快照：

```powershell
python scripts/create_db_snapshot.py `
  --source "<ACTIVE_APP_DIR>\history.db" `
  --output "<TEST_DIR>\history-readonly.snapshot.db"
```

预期输出：

```text
history-readonly.snapshot.db
history-readonly.snapshot.db.manifest.json
```

命令必须返回：

```text
integrity_check = ok
```

该命令使用 SQLite online backup API，不手工复制 WAL/SHM。

## 第三步：检查混合任务状态

```powershell
python scripts/inspect_db_snapshot.py `
  --snapshot "<TEST_DIR>\history-readonly.snapshot.db"
```

至少记录：

- `works` 和 `downloads` 总行数；
- `completed`、`failed`、`paused`、`queued`、`downloading`、`resuming` 和历史
  状态字符串的数量；
- `active_or_attention_download_rows`；
- snapshot 时间和 SHA-256 manifest 验证结果；
- `integrity_check`。

下载器仍在运行时，两次快照之间的数量可能变化，这不表示数据库不一致。所有比较
必须基于同一份快照。

## 第四步：只观察 UI

可以观察和截图当前运行中的 UI，但不得点击任何会改变队列状态的控件。记录：

- 页面是否保持响应；
- completed、failed、paused、queued、downloading 卡片是否正常显示；
- UI 状态数量与同一时段快照是否大致一致；
- 是否存在布局拥挤、文字截断、错误按钮、陈旧进度或状态语义不一致。

这里只是观察，不代表当前 UI 已通过质量验收。


## 第五步：隔离的真实下载和 UI Smoke

该步骤不是在正式程序中添加任务。使用两个全新的空目录：

```text
D:\ARSM-Smoke\live-download
D:\ARSM-Smoke\ui
```

真实站点最小文件测试：

```powershell
python scripts/live_download_smoke.py `
  --sandbox "D:\ARSM-Smoke\live-download" `
  --rj RJ01575399 `
  --max-bytes 67108864
```

UI 使用本地固定服务器，避免把视觉验收与真实站点波动混在一起：

```powershell
python scripts/fake_asmr_server.py --port 8765
```

另一个终端：

```powershell
python scripts/run_ui_smoke.py `
  --sandbox "D:\ARSM-Smoke\ui" `
  --rj RJ99999999 `
  --mirror http://127.0.0.1:8765 `
  --view desktop
```

记录下载卡片、进度、暂停恢复、重连、失败提示和打开目录。正式队列不执行任何控制操作。

## 第六步：External Intake 只读计划

正式队列仍活跃时，不对真实目录执行 external intake。只有复制目录与 snapshot DB
可以用于计划和沙盒验收。真实执行按钮继续冻结。

## 通过条件

只读验收满足以下条件才算通过：

- 干净仓库副本 portable tests 通过；
- 在线快照创建成功且 manifest 验证通过；
- snapshot `integrity_check` 为 `ok`；
- 能完整报告混合任务状态；
- 独立 live download 的最终大小和报告通过；
- 独立 Flet UI sandbox 的状态和文件结果一致；
- 正式队列、文件、数据库、依赖和设置均未发生变化。

真实小批量文件操作继续阻塞，直到目标 RJ 不再含有
`queued/downloading/resuming/paused/failed` 行，并且复制沙盒已通过 T6。
