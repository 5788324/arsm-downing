# arsm-downing 接手审计

> 状态更新（2026-07-20）：TAKEOVER-T0/T1/T2/T3 已完成多层硬冻结、计划 schema v3、配置化路径、LibraryVault 快照、四表事务、逐文件映射、staging、关键哈希、Journal、回滚与崩溃恢复；62 项便携测试通过。真实 Tools/CLI/正式资源库执行继续冻结。

- 日期：2026-07-18
- 基线：`main@1f33595b8fb3e7d895ae6bca1f907186d836bc60`
- 结论：`NEEDS_FIX`
- 项目判断：可以继续维护，不需要推倒重写
- 暂停项：外部资源接入的真实批量执行

## 1. 总体判断

项目已经具备下载调度、SQLite 数据层、资源库 UI、迁移工具、backlog 工具和大量回归脚本。主要问题不是基础功能缺失，而是近期 `external_intake` 把目录移动、隔离、数据库更新和元数据刷新集中到一个模块，安全边界与测试覆盖尚未闭合。

当前优先级：

1. 固定事实与文档
2. 收口 external intake
3. 建立可重复测试和 CI
4. Windows 本机只读验收
5. 小批量真实验收
6. 再进入播放器阶段

## 2. 仓库与流程问题

- 接手前无开放 PR，也无 Issue 台账。
- 历史工作主要直接提交到 `main`。
- 没有标准 GitHub Actions CI。
- 测试主要是 `scripts/test_*.py` 的脚本式回归。
- README、路线图、AI 分工和最近代码状态存在明显漂移。

接手后采用：

```text
chatgpt/* 分支 -> Draft PR -> 审查/测试 -> main
```

## 3. 文档漂移

### README

README 仍把项目描述为旧版单一下载器，并强调 `queue.json`。当前实际架构已经是单体 arsm-suite，`history.db` 是业务真源，正式 DB 访问应经过 `LibraryVault`。

### PROJECT_ROADMAP

路线图仍把 P1/P2/P3/P4.5 列为近期任务，但代码已经推进到资源库 UI、backlog 管理、零异常清理和外部资源接入。

### WORKLOG

WORKLOG 未完整记录最后几次 external intake 提交。

### 本机状态

2026-06-28 文档中的 `works=184`、`downloads=0`、`integrity=ok` 只能视为历史快照，不能当作 2026-07-18 实时结果。

## 4. external intake 的 P0 问题

### P0-01：数据库入口不统一

`tools/external_intake.py` 直接连接 SQLite 并修改业务表，绕过 `LibraryVault`。这破坏了统一写锁、事务封装和应用内单例约束。

### P0-02：重复 RJ 可能影响正常主记录

重复目录被标记为隔离时，执行逻辑按 RJ 号处理数据库记录，不能可靠区分正常主目录与重复副本。需要改为路径级校验，默认保留正常主记录。

### P0-03：文件与数据库缺少原子恢复

当前流程先移动文件，再更新数据库；异常后会继续处理下一项。SQLite 回滚不能自动恢复文件系统，现有 rollback plan 也不足以逐文件恢复。

### P0-04：blocker 与 quarantine 语义冲突

所有需要隔离的目录都会成为全局 blocker，因此受保护入口无法真正执行隔离分支。应拆分：

```text
fatal_blocker
review_required
quarantine_action
warning
```

### P0-05：目标路径预检不足

缺少目标已存在、同名文件、Windows 保留名、净化后空标题、路径过长、源目标嵌套等完整预检。

### P0-06：根目录不存在时 schema 不稳定

扫描根目录不存在时返回字段不完整，而 CLI/UI 使用固定键访问，可能触发异常。任何扫描结果都应返回固定 schema。

### P0-07：元数据刷新副作用不明确

当前刷新流程新建 `LibraryVault`、启动 Orchestrator worker 并调用 `prepare_work`。需要拆成纯元数据服务，明确允许写入范围，禁止意外启动下载任务。

## 5. P1 问题

- ToolsView 在 UI 事件中同步执行扫描、文件移动和 DB 操作，可能冻结窗口。
- 计划报告只保存前 50 个目录，不足以作为完整审计依据。
- 依赖未锁版本。
- 没有统一测试命令。
- 没有 CI。

## 6. 测试审计

现有 external intake 测试覆盖了 RJ 归一化、目录分类、标题净化、track 提取和基础 blocker 语义，但仍缺少：

- 临时 SQLite fixture
- 真实执行测试
- 重复 RJ 主记录保护
- 目标冲突
- 文件移动失败注入
- DB 写入失败注入
- 自动回滚
- 根目录不存在
- 报告完整性

当前测试还会读取真实 `E:\arsm`，不能在通用环境稳定复现。默认测试必须完全使用临时目录和临时数据库。

## 7. 解除 STOP 的验收门槛

- [ ] 业务 DB 写入全部收口到 LibraryVault/service
- [ ] 重复 RJ 不影响正常主记录
- [ ] 固定 plan schema
- [ ] 完整目标冲突预检
- [ ] 每个作品具备可验证自动恢复
- [ ] 审计报告不截断
- [ ] 默认单元测试不依赖 `E:\arsm`
- [ ] 失败注入测试通过
- [ ] 临时目录集成测试通过
- [ ] Windows 本机只读 dry-run 通过
- [ ] 真实资源库最多 1~3 个作品的小批量验收通过

## 8. 接手结论

```text
下载器、资源库和 SQLite 基础：保留
external intake 当前真实执行：STOP
播放器开发：后移
下一步：安全重构 + portable tests + 本机只读验收
```
