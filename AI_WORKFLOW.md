# AI_WORKFLOW.md

# arsm-downing / arsm-suite AI 协作与交付工作流

> 更新：2026-07-20
> 适用范围：当前项目的开发、测试、Git、文档、Windows 验收和发布

## 1. 当前分工

```text
ChatGPT：主要开发者和项目负责人
Codex：Windows/Flet/真实目录/真实数据库/打包验收
用户：需求与最终范围决策，不承担日常开发、测试、Git 或发布
DeepSeek/OpenCode：仅在 ChatGPT 明确分配时承担低风险批量工作
```

### ChatGPT 负责

- 架构、任务拆分和风险边界
- 本地批量修改代码
- 当前环境可完成的测试和代码审查
- README、CURRENT_STATE、WORKLOG、路线图和交接文档
- 分支、提交、PR、Issue 和合并前检查
- 根据 Codex 的实机报告完成必要修复

### Codex 只负责

- Windows 真实运行环境
- Flet GUI 行为与显示
- 用户真实 `E:\arsm` 的只读观察，以及通过在线备份生成的 `history.db` 快照验收
- 当前环境无法覆盖的网络、文件锁、路径和打包问题
- 最终便携包/安装包验证

Codex 不负责日常项目管理，不承担可在当前环境完成的普通编码任务。

## 2. Git 工作流

```text
一个任务包 = 一个分支 + 一个 PR
本地批量修改后统一提交
通常只推送一次
只有真实 CI 或实机验收失败时，最多追加一次修复推送
禁止通过 GitHub 内容接口逐文件形成大量零碎提交
main 只接收通过测试和审查的 PR
```

当前接手任务使用：

```text
分支：chatgpt/takeover-20260718
PR：#1
```

接手分支在最终推送前应整理为清晰、可审查的提交历史。

## 3. Google Drive 的定位

Google Drive 是网络受限环境下的代码运输和验收材料通道，不替代 GitHub：

```text
Google Drive：Git Bundle、完整快照、Windows 验收日志、截图、发布包
GitHub：正式仓库、Issue、PR、代码审查、CI、合并和版本历史
```

建议只传输 `git bundle`，不要在 Google Drive 同步目录中长期直接运行 `.git` 工作区。

## 4. 开发顺序

每轮任务按以下顺序执行：

```text
1. 核对当前分支、任务边界和禁止事项
2. 本地批量开发
3. 使用临时目录、临时 SQLite 和模拟网络运行自动测试
4. 更新核心文档
5. 检查 git diff、敏感路径和真实数据副作用
6. 形成一个正式提交
7. 需要时推送并更新 PR
8. 仅把必须依赖 Windows 的验收交给 Codex
```

## 5. 数据与文件安全边界

项目仅供个人使用，不采用企业级繁琐流程，但以下操作必须保持 fail-closed：

- 文件移动、隔离、覆盖或删除
- 真实 `history.db` 写入、迁移和批量状态修改
- 下载断点文件 `.part` 的重置或删除
- 资源库批量重建

默认规则：

```text
dry-run 优先
测试不使用真实 E:\arsm
测试不连接真实 history.db
活跃下载存在时，不升级生产依赖、不运行维护命令、不手工复制 DB/WAL/SHM
真实状态核验只能使用在线只读 snapshot + manifest
失败不得报告成功
数据库与文件系统更新必须具有可核验恢复路径
```

## 6. 每轮交付记录

每轮至少记录：

- 完成范围
- 修改文件
- 测试命令与结果
- 是否访问真实数据库
- 是否移动或删除真实文件
- 已知限制
- 下一轮任务
- Git 状态和提交

以上内容同步到 `WORKLOG.md`；当前事实同步到 `CURRENT_STATE.md`；后续任务同步到 `NEXT_TASK_ROADMAP.md`。

## 7. 当前任务顺序

```text
1. external intake 真实执行硬冻结（已完成）
2. external intake 计划模型与纯扫描收口（已完成）
3. external intake LibraryVault 快照与路径事务（已完成）
4. external intake 逐作品文件执行与自动恢复（沙盒已完成）
5. 统一测试、CI、在线 DB snapshot（已完成）
6. 下载核心 416 / Range / .part / 取消恢复与隔离 UI smoke（代码级已完成）
7. T6 复制资源库沙盒执行与故障恢复（已完成）
8. Tools 缓存/VACUUM/队列预览和 backlog 安全闭环（已完成）
9. Windows 在线快照、真实 ASMR.one 小样本与 Flet 视觉验收（并行待 Codex）
10. 迁移、数据库 Schema 和资源库 rebuild 一致性（已完成）
11. 100+ 混合任务清空后进行 T7 Windows 小批量验收
12. 0.9.0-rc.1 构建和交接（代码级已完成，待 GitHub/Windows 证据）
```


## Windows 实机验收入口

必须使用独立证据目录，不在正式程序目录安装依赖或运行测试：

```powershell
.\scripts\run_windows_acceptance.ps1 `
  -EvidenceDir "D:\ARSM-Acceptance" `
  -ActiveDb "<正式程序目录>\history.db" `
  -LaunchUi
```

Codex 负责执行和填写 `ui-observation.json`；ChatGPT 负责分析结果、修复代码和维护 Git/文档。
