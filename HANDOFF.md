# ARSM Suite 当前交接

## 当前版本

```text
正式版本：v0.9.0-rc.1
main：9f292e7947804f2e4d53290039501f79c6d1805d
当前分支：chatgpt/optimize-o1-20260722
当前阶段：O1 下载队列与调度优化
```

## 当前事实

- 主要功能开发已完成；
- 正式 Windows Pre-release 已发布；
- portable CI：Ubuntu / Windows 205/205 PASS；
- 本地和远端旧分支已清理，只保留 `main` 后重新创建当前 O1 分支；
- 正式 `history.db`、`E:\arsm` 和现有 100+ 任务未被开发环境修改；
- Codex 正在补齐 Windows Desktop 和真实网络现场证据；
- 优化总台账：GitHub Issue #5。

## 本轮 O1

当前已开始：

- 下载队列任务级 Read Model；
- 一次 SQL 聚合任务和文件状态；
- 队列分页和状态过滤基础；
- 批量 RJ 输入预览、去重和分类；
- 单元测试。

后续：

- 接入 DownloadView；
- 增加独立元数据并发池；
- 审计实时进度 SQLite 写入频率；
- Windows 实机验收；
- 发布 `0.9.0-rc.2`。

## Codex 当前任务

按以下文档完成正式 Release 实机验收：

[`docs/CODEX_WINDOWS_ACCEPTANCE_RC1.md`](docs/CODEX_WINDOWS_ACCEPTANCE_RC1.md)

Codex只提交：

- 报告；
- 日志；
- 截图；
- 现场结论。

不要在验收中直接修改代码。

## 禁止事项

```text
External Intake 正式 Execute
正式资源库批量迁移
正式 VACUUM
正式 backlog execute
T7 目录整理
覆盖现有程序目录
修改现有 100+ 任务路径或状态
```

## 下一位 AI 的入口

1. 阅读 `CURRENT_STATE.md`；
2. 阅读 `NEXT_TASK_ROADMAP.md`；
3. 查看 Issue #5；
4. 核对当前 PR 和 CI；
5. 继续 O1，不扩大到托盘和设置热更新；
6. Windows 专属行为交给 Codex。
