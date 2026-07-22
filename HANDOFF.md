# ARSM Suite 当前交接

## 当前基线

```text
正式版本：v0.9.0-rc.1
main：9f292e7947804f2e4d53290039501f79c6d1805d
当前分支：chatgpt/optimize-o1-20260722
当前 PR：#6
当前阶段：O1 下载队列与调度优化
```

## 当前事实

- 主要功能开发和 RC1 发布已完成；
- Windows Pre-release 已发布；
- 仓库旧分支和旧本地目录已清理；
- Codex正在执行正式 RC1 Windows 实机验收；
- 正式 `history.db`、`E:\arsm` 和现有 100+ 任务未被优化开发访问；
- 优化总台账：Issue #5。

## PR #6 已完成代码

- 下载队列任务级 Read Model；
- `works + downloads` 聚合和 orphan download 兼容；
- 独占状态、分页、过滤和统一摘要；
- DownloadView 接入 Snapshot；
- 默认隐藏已完成任务；
- 批量 RJ 预览、去重、查重和确认后入队；
- `metadata_concurrency` 独立 Semaphore；
- 设置页和示例配置；
- 分块进度保持内存，不按 chunk 写 SQLite；
- 检查点、暂停、失败、完成和退出持久化；
- 220 项本地隔离测试通过。

## 当前待完成

1. PR #6 Ubuntu / Windows CI；
2. 真实 Flet 0.27.6 验证；
3. Codex RC1 实机报告；
4. 为 O1 构建 Windows Artifact；
5. Codex完成 O1 筛选、分页、批量预览、暂停和恢复验收；
6. 审查后合并并发布 `0.9.0-rc.2`。

## Codex RC1 验收入口

[`docs/CODEX_WINDOWS_ACCEPTANCE_RC1.md`](docs/CODEX_WINDOWS_ACCEPTANCE_RC1.md)

Codex只提交报告、日志、截图和现场结论；不直接改代码。

## 禁止事项

```text
External Intake 正式 Execute
正式资源库批量迁移
正式 VACUUM
正式 backlog execute
T7 目录整理
覆盖现有程序目录
修改现有 100+ 任务路径或状态
删除或重置旧 .part
```

## 下一位 AI 入口

1. 阅读 `CURRENT_STATE.md`；
2. 阅读 `NEXT_TASK_ROADMAP.md`；
3. 查看 Issue #5 和 PR #6；
4. 核对 PR CI；
5. 不扩大到 O2/O3；
6. Windows 专属行为交给 Codex。
