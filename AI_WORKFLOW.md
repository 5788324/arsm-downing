# ARSM Suite AI 协作与交付工作流

> 更新：2026-07-22

## 分工

```text
ChatGPT：架构、主要开发、测试、文档、Git/PR 和最终审查
Codex：Windows Desktop、真实网络、文件锁、打包和现场验收
用户：需求与范围决策，只接收最终成果
DeepSeek/OpenCode：仅在明确分配时处理低风险批量任务
```

## Git 规则

```text
一个任务包 = 一个分支 + 一个 PR
从最新 main 建分支
本地批量修改
通常一次正式提交和推送
真实 CI 失败最多一次修复推送
禁止逐文件远程形成大量小提交
main 只接收通过测试和审查的 PR
合并后删除任务分支
```

当前任务：

```text
Issue：#5
分支：chatgpt/optimize-o1-20260722
范围：O1 下载队列与调度优化
```

## 开发顺序

1. 核对 `main`、Issue 和任务边界；
2. 批量修改代码和文档；
3. 使用临时目录、临时 SQLite 和模拟网络测试；
4. 更新 README、CURRENT_STATE、路线图、交接和工作记录；
5. 检查敏感文件和真实数据副作用；
6. 形成一个正式提交；
7. 建立 Draft PR；
8. CI 全绿后交给 Codex 做必要 Windows 验收；
9. 审查、合并、删除分支。

## 数据安全

```text
history.db / SQLite = 唯一业务真源
LibraryVault = 正式数据库入口
测试不访问 E:\arsm
测试不连接正式 history.db
不手工复制活跃 WAL/SHM
不删除或重置旧 .part
不批量改写旧任务路径
文件写操作必须有 dry-run 和恢复路径
```

## Codex 验收规则

- 使用正式 Release 或 PR Artifact；
- 只在独立目录运行；
- 不覆盖正式程序；
- 不操作正式数据库和下载队列；
- 保存截图、日志、SHA-256 和 Markdown 报告；
- 失败只报告证据，不直接开发修复。

正式 RC1 验收入口：

[`docs/CODEX_WINDOWS_ACCEPTANCE_RC1.md`](docs/CODEX_WINDOWS_ACCEPTANCE_RC1.md)

## 文档同步

每轮至少同步：

- `README.md`
- `CURRENT_STATE.md`
- `NEXT_TASK_ROADMAP.md`
- `HANDOFF.md`
- 对应 `docs/WORKLOG_*.md`
- GitHub Issue / PR 描述

`WORKLOG.md` 继续保留完整历史；新阶段可增加独立工作日志并从 README 链接。
