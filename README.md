# arsm-downing / ARSM Suite

面向个人本地使用的 Windows ASMR/RJ 下载、资源库与维护工具。

```text
Python + Flet + SQLite + asyncio + aiohttp
```

当前应用保留四个主页面：

- 下载中心；
- 资源库；
- 系统工具；
- 设置。

原“统计与成就”页面已在 `0.9.0-rc.2` 候选中删除。统计数据继续由资源库和 Tools 的实际数据视图承担，不再维护单独成就系统。

## 当前版本

```text
已发布候选：0.9.0-rc.1
当前开发候选：0.9.0-rc.2
```

`0.9.0-rc.1` 已完成：

- Ubuntu / Python 3.10 CI：PASS；
- Windows / Python 3.12 CI：PASS；
- portable pytest：205/205 PASS；
- Windows PyInstaller one-folder 构建：PASS；
- Windows 11 Desktop 三次启动与正常关闭：PASS；
- 真实 ASMR.one 元数据、文件列表、下载、暂停和恢复：PASS_WITH_NOTES。

Windows 隔离验收确认：

- 9 个不同 RJ 已持久化；
- 下载表生成 475 条文件记录；
- 全部暂停后 466 条处于 paused，非空 `.part` 保留；
- 全部继续后恢复到 downloading/queued；
- 最终非空 MP3 文件存在；
- 正式 `history.db`、`E:\arsm` 和现有任务未被触碰。

验收发现下载页底部汇总未在批量动作后刷新。该问题已进入 `0.9.0-rc.2` 修复。

## 0.9.0-rc.2 下载页修复

- “全部暂停”和“全部继续”执行完成后重新从 SQLite 加载队列；
- 队列汇总不再停留在旧状态；
- 顶部显示全部下载的实时总速度；
- 每张作品卡显示该作品速度，不再重复显示全局速度；
- 完成作品立即从活动下载队列移除，历史仍保留在 SQLite 和资源库；
- 批量按钮根据当前状态自动启用或禁用；
- 删除“统计与成就”页面和完成后的成就触发。

## 核心能力

### 下载

- 单个和批量 RJ 输入；
- 元数据缓存和递归音轨；
- 下载队列、暂停、恢复和失败重试；
- HTTP 200/206/416 与严格 `Content-Range`/大小验证；
- `.part` 断点续传；
- metadata / cover / download 三通道代理；
- 音频标签与封面写入；
- 全局总网速、作品速度和 ETA。

### 资源库

- `history.db` 中的 `works/library_items/library_index`；
- 作品卡片、封面、搜索和分页；
- 异常识别；
- 快照式 rebuild 和原子索引替换；
- 打开本地目录。

### 维护工具

- 下载状态诊断；
- 缓存和队列预览；
- 活跃任务感知的 VACUUM；
- backlog 只读预览；
- 迁移 dry-run、manifest、四表事务和回滚；
- External Intake 计划、Journal 和沙盒验收。

## 架构约束

```text
history.db / SQLite = 唯一业务真源
LibraryVault = 唯一正式数据库访问入口
UI 不直接 sqlite3.connect()
queue.json 不作为历史下载状态真源
扫描 JSON / manifest 只作为报告、缓存或审计证据
```

禁止用已放弃的 ARSM Library v2 替换当前数据库、下载表或下载引擎。允许吸收的仅是 Service/read model、批量快照、metadata queue、批量预览、页面生命周期和状态迁移设计。

## 启动

```powershell
python -m pip install -r requirements.txt
Copy-Item config.example.json config.json
python main.py
```

## 测试

```powershell
python -m pip install -r requirements-dev.txt
python -m compileall -q core ui tools tests scripts main.py
python -m pytest
```

`0.9.0-rc.2` 本轮本地结果：

```text
compileall：PASS
portable tests：211/211 PASS
```

本地容器没有真实 Flet 0.27.6，因此本地 UI 单元测试使用临时接口桩；GitHub CI 必须使用锁定的真实 Flet 再验证 Linux/Windows。

## Windows 构建

```powershell
.\scripts\build_windows.ps1
```

## 当前冻结操作

```text
External Intake 正式 execute
正式资源库迁移、移动、隔离和删除
正式 history.db VACUUM
正式 backlog execute
T7 正式目录整理
覆盖仍在下载的正式程序目录
```

## 下一阶段

完成 `0.9.0-rc.2` CI 后进入 `TAKEOVER-T10`：

- 下载只读模型和 DownloadService；
- 100+ 任务批量队列快照；
- 批量 RJ 预览和完整查重；
- metadata queue 与 audio queue 分离；
- 页面 active/inactive 生命周期；
- 显式状态迁移规则。

## 文档

- [`CURRENT_STATE.md`](CURRENT_STATE.md)
- [`NEXT_TASK_ROADMAP.md`](NEXT_TASK_ROADMAP.md)
- [`PROJECT_ROADMAP.md`](PROJECT_ROADMAP.md)
- [`WORKLOG.md`](WORKLOG.md)
- [`DECISIONS.md`](DECISIONS.md)
- [`HANDOFF.md`](HANDOFF.md)
- [`docs/POST_RC_OPTIMIZATION_BACKLOG.md`](docs/POST_RC_OPTIMIZATION_BACKLOG.md)
- [`docs/archive/WORKLOG_20260627_20260721.md`](docs/archive/WORKLOG_20260627_20260721.md)

## License

Based on `takoyune/asmr.one-downloader` and licensed under the MIT License. See [`LICENSE`](LICENSE).
