# ARSM Suite 交接说明

> 更新时间：2026-07-23

## 1. 当前版本与基线

```text
版本：0.9.0-rc.1
主分支：main
main commit：9f292e7947804f2e4d53290039501f79c6d1805d
PR #1：已合并
```

当前不是“等待 RC 合并”阶段，而是：

```text
Post-RC 稳定化与大队列优化
```

## 2. 已确认事实

- 下载核心、资源库、迁移、External Intake 沙盒、Tools 和构建链已完成 RC 收口；
- portable tests：205/205 PASS；
- Ubuntu/Python 3.10 与 Windows/Python 3.12 CI 通过；
- Windows one-folder Artifact 通过；
- 发布 ZIP SHA-256 已复核；
- Windows 隔离路径 EXE 启动和状态文件边界通过；
- 自动结论为 `PASS_WITH_NOTES`；
- 正式 `history.db`、真实 `E:\arsm` 和 100+ 混合任务未被开发环境修改。

发布包：

```text
ARSM-Suite-0.9.0-rc.1-windows-x64.zip
SHA-256：b60125d5fddebd056d292a8dccb485d512d52eb65865db9534e1a874de20f2cb
```

## 3. 尚未完成的证据

1. 用户桌面 Flet Desktop 五页视觉和鼠标交互；
2. 真实 ASMR.one 网络小样本；
3. Windows Defender、长路径和文件占用现场观察；
4. 维护窗口中的正式数据库 snapshot 和小批量目录验收。

DeepSeek 没有视觉能力。后续不得让其根据截图自行给出视觉 PASS；它只能运行明确脚本和返回原始证据。

## 4. 已放弃分支

`ARSM-Library-v2-source-20260722` 已放弃，不继续独立开发，不合入当前主线。

允许吸收：

- Service/read model；
- 批量队列快照；
- 元数据与下载池分离；
- 批量添加预览；
- 显式状态迁移；
- 页面 active/inactive；
- 资源库详情侧栏；
- 后续托盘概念。

禁止吸收：

```text
library.db
v2 download_tasks/download_files
v2 下载引擎
v2 非原子设置保存
正式库直入逻辑
不继承旧任务的切换方案
整套未验收 UI/托盘代码
```

## 5. 下一位 AI 的首要任务

执行 `TAKEOVER-T10：Queue Service 与大队列性能优化`。

必须先阅读：

```text
CURRENT_STATE.md
NEXT_TASK_ROADMAP.md
docs/POST_RC_OPTIMIZATION_BACKLOG.md
DECISIONS.md
```

T10 主要内容：

1. 下载只读模型；
2. LibraryVault 批量队列快照；
3. 轻量 DownloadService；
4. 批量 RJ 预览；
5. metadata queue 与 download queue 分离；
6. 页面生命周期；
7. 状态迁移规则和测试。

T10 边界：

```text
不改数据库表结构
不替换下载核心
不改 .part 语义
不访问正式数据库和 E:\arsm
不加入托盘
不开发播放器
```

## 6. Git 与交付要求

```text
一个任务 = 一个分支 + 一个 PR
批量修改后一个正式提交
通常只推送一次
真实 CI 失败最多追加一次修复推送
禁止逐文件远程提交形成零碎历史
文档必须与代码同轮更新
```

建议分支：

```text
chatgpt/t10-queue-service
```

建议 PR：

```text
perf: optimize queue snapshots and metadata scheduling
```

## 7. 测试要求

默认：

```powershell
python -m compileall -q core ui tools tests scripts main.py
python -m pytest
```

T10 还需要：

- 100+ 任务批量快照一致性；
- N+1 查询上限；
- metadata 并发上限；
- 批量预览查重；
- 页面激活生命周期；
- 状态迁移合法/非法路径；
- 现有 205 项无回归。

测试必须使用临时 SQLite、临时目录和本地 fake server。

## 8. 禁止直接执行

```text
python tools/external_intake.py --execute --confirm-bulk
正式资源库批量迁移、移动、隔离或删除
正式 history.db VACUUM
正式 backlog execute
覆盖当前仍在下载的程序目录
手工删除或重置 .part
T7 真实目录整理
```

## 9. Windows 验收分工

ChatGPT：

- 设计验收步骤；
- 检查机器日志和截图；
- 负责视觉判断；
- 判断 PASS/NEEDS_FIX/BLOCKED。

本机执行者：

- 只在隔离目录运行；
- 不评价截图；
- 不修改代码或生产数据；
- 原样返回日志、截图和错误。

用户：

- 只承担无法远程完成的最少点击和上传证据；
- 不负责测试设计、Git、构建或发布。

## 10. 当前结论

```text
主线可继续开发。
下一轮应先做低风险大队列优化，不应重新开启 v2，不应触碰维护窗口任务。
```
