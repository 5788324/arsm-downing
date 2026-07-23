# ARSM Suite 当前阶段工作日志

> 2026-06-27 至 2026-07-21 的完整历史见：  
> [`docs/archive/WORKLOG_20260627_20260721.md`](docs/archive/WORKLOG_20260627_20260721.md)

## 当前快照

```text
已发布候选：0.9.0-rc.1
当前开发候选：0.9.0-rc.2
当前任务：T9.1 下载页现场缺陷修复
下一任务：T10 Queue Service 与大队列性能
本地测试：211/211 PASS
正式数据：零访问、零修改
```

## 2026-07-21：0.9.0-rc.1 合并

- PR #1 合并到 `main`；
- 合并提交 `9f292e7947804f2e4d53290039501f79c6d1805d`；
- Ubuntu/Windows CI 和 205 tests 通过；
- Windows one-folder Artifact 通过；
- 自动结论 `PASS_WITH_NOTES`。

## 2026-07-22：v2 审计与放弃

- `ARSM-Library-v2-source-20260722` 不作为替代版本；
- 不合并其数据库、下载引擎和 UI；
- Service/read model、批量快照、metadata queue、批量预览、状态迁移和页面生命周期纳入 T10。

## 2026-07-23：Post-RC 文档重整

- PR #7 合并；
- README、CURRENT_STATE、路线图、交接、决策和工作流与 RC 合并后的事实对齐；
- 旧 2700+ 行 WORKLOG 完整归档。

## 2026-07-23：Windows 真实下载验收复核

### 输入

`CODEX_WINDOWS_ACCEPTANCE.md`

### 已确认

- Windows 11 三次启动和标题栏正常关闭；
- 隔离配置保存并重启保留；
- 9 个不同 RJ 和 475 条下载记录；
- 暂停后 466 paused，4 个非空 `.part` 合计约 30.3 MB；
- 重启后暂停状态保持；
- 全部开始后恢复 downloading/queued；
- `.part` 增长到约 54.0 MB；
- 最终 MP3 14,017,924 字节；
- 正式环境未触碰。

### 发现

批量恢复后下载页汇总仍显示旧状态：

```text
下载中 0、排队 0、暂停 9
```

### 判定

核心批量动作有效；缺陷位于 UI 刷新和汇总层。

## 2026-07-23：T9.1 下载页现场缺陷修复

### 执行者

```text
ChatGPT
```

### 目标

在开始 T10 前修复现场验收发现的问题，并删除无用成就页。

### 实际完成

1. 新增 `reload_queue_from_database()`；
2. 全部暂停/继续结束后通过 UI queue 触发一次 DB 重载；
3. 汇总按活动作品重新计算；
4. 增加实时总网速；
5. 卡片改用 `work_speed_bps`；
6. 完成作品立即移出活动队列；
7. 批量按钮改为“全部暂停/全部继续”，并按状态禁用；
8. 从运行时导航移除 Dashboard/“统计与成就”，成就检查改为兼容 no-op；
9. RC1 界面实现保留为 `app_base.py` / `download_view_base.py`，RC2 通过小型兼容层覆盖，待 T10 再合并整理；
10. 旧 achievements 配置字段暂留兼容；
11. 版本改为 `0.9.0-rc.2`；
12. 新增 6 项回归测试。

### 修改文件

```text
core/version.py
ui/app.py
ui/app_base.py（RC1 兼容基线）
ui/views/download_view.py
ui/views/download_view_base.py（RC1 兼容基线）
tests/test_download_ui_semantics.py
tests/test_app_background.py
tests/test_import_smoke.py
tests/test_release_packaging.py
README.md
CURRENT_STATE.md
NEXT_TASK_ROADMAP.md
HANDOFF.md
WORKLOG.md
DECISIONS.md
```

### 数据影响

```text
正式 DB：未访问
真实 E:\arsm：未访问
正式任务：未修改
下载核心：未修改
文件删除：无；“统计与成就”已从运行时导航移除
```

### 测试

```text
python -m compileall -q core ui tools tests scripts main.py：PASS
python -m pytest：211/211 PASS
```

本地容器无真实 Flet，UI 测试通过临时接口桩运行；GitHub CI 必须使用真实锁定依赖复核。

### 剩余

- GitHub Linux/Windows CI；
- 10 个输入/9 distinct 原因由 T10 批量预览明确呈现；
- 合并后开始 T10。
