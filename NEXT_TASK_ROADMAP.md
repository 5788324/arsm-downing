# NEXT_TASK_ROADMAP.md

# arsm-downing 接手后详细任务路线图

> 起点：2026-07-18  
> 基线：`main@1f33595`  
> 当前阶段：`TAKEOVER-T4`（`TAKEOVER-T0/T1/T2/T3` 已于 2026-07-20 完成）

## 总原则

```text
不推倒重写
不直接在 main 开发
不把 UI 改动与高风险 DB/文件操作混成一个 PR
不使用真实 E:\arsm 作为默认测试夹具
不在安全收口前开发播放器
```

## TAKEOVER-T0：接手基线与冻结

### 目标

建立可信的当前状态，冻结 external intake 真实执行。

### 任务

- [x] 确认仓库权限、默认分支、近期提交、PR/Issue 状态
- [x] 建立接手分支
- [x] 新增 `CURRENT_STATE.md`
- [x] 新增 `docs/TAKEOVER_AUDIT_20260718.md`
- [x] 新增本路线图
- [x] 重写 README，使其反映 arsm-suite 当前架构
- [x] 更新 AI_WORKFLOW 为当前 ChatGPT/Codex 分工
- [x] 在 WORKLOG 追加接手记录
- [x] 给 external intake UI 增加明确 STOP 提示并禁用执行按钮
- [x] 在 `execute_normalize()` 最深层入口增加副作用前硬冻结
- [x] CLI `--execute` 固定以退出码 2 拒绝
- [x] 建立临时目录/临时 SQLite 的便携回归测试

### 验收

```text
PASS（2026-07-20）
文档与当前代码阶段一致
核心执行、元数据刷新、CLI、UI 均 fail-closed
12/12 external-intake 便携测试通过
未访问真实 E:\arsm 或 history.db
```

## TAKEOVER-T1：计划模型与纯扫描收口

### 状态

```text
PASS（2026-07-20）
```

### 已完成

- [x] 固定 `ExternalIntakePlan` schema：root、root_exists、scanned_top_dirs、unique_rj、actions、fatal_blockers、review_required、quarantine_actions、warnings、can_execute
- [x] 所有失败和空结果路径保持同一 schema
- [x] 六类目录分类：already_normalized、needs_title_layer、needs_rename_top_level、quarantine_candidate、duplicate_review、fatal
- [x] 扫描根目录和隔离目录改为配置，不再硬编码用户盘符
- [x] 增加绝对路径、文件系统根目录、路径包含、符号链接和目标逃逸检查
- [x] 增加目标路径已存在冲突检查
- [x] 重复 RJ 的所有候选均进入人工复核，不自动选择主目录
- [x] 报告保存全部 actions，不截断前 50 项
- [x] UI 只显示摘要和前 15 项，完整报告写文件
- [x] UI 扫描使用后台线程，设置页提供两个路径配置项
- [x] 删除旧的文件移动和业务 SQLite 写入实现

### 验收

```text
20/20 portable tests passed
60-action report completeness passed
missing/relative/unsafe root tests passed
duplicate RJ review tests passed
target conflict fatal tests passed
config round-trip tests passed
真实文件和数据库零副作用
```

## TAKEOVER-T2：数据库服务收口

### 状态

```text
PASS（2026-07-20）
```

### 已完成

- [x] `LibraryVault` 支持指定数据库路径、上下文关闭和 `mode=ro` 只读打开
- [x] 增加 RJ 快照接口：works、metadata title/tracks、library_items、library_index、downloads
- [x] `ExternalIntakePlan` schema v2 附加 preimage token、主路径、pending 和索引路径
- [x] Tools 页复用 AppController 现有 Vault，不创建新实例
- [x] external intake 工具移除业务 `sqlite3.connect`，只读核验通过 Vault
- [x] 新增四表统一路径事务：works、downloads、library_items、library_index
- [x] 使用 `BEGIN IMMEDIATE`、写锁和路径组件替换，不使用 SQL 字符串 `REPLACE`
- [x] 成功结果包含 preimage/postimage/token/updated_rows/transaction_id
- [x] SQLite 故障 rollback 全部表并保留 preimage
- [x] 重复副本不能覆盖正常主记录；不按 RJ 号删除记录
- [x] 同 RJ source/target index 冲突、其他 RJ 目标占用、第三路径不一致均 fail-closed
- [x] 全新数据库补齐 `library_items` 基础 schema

### 验收

```text
tools/external_intake.py 无业务 sqlite3.connect
UI 无新增 LibraryVault 实例
40/40 external-intake portable tests passed
重复 RJ 主记录保护 passed
SQLite failure rollback passed
read-only CLI database hash unchanged
真实文件与真实数据库零副作用
```

## TAKEOVER-T3：逐作品执行与自动恢复

### 状态

```text
PASS（2026-07-20，沙盒执行层）
```

### 已完成

- [x] 计划 schema v3 生成完整逐文件 source/target 映射
- [x] source manifest token 在执行前重新校验计划漂移
- [x] 每个作品独立 Journal 与状态时间线
- [x] 目标盘 staging copy；源目录同盘 rollback 暂存
- [x] staging 和 target 均校验相对路径、数量、总大小、单文件大小和关键哈希
- [x] Title 层映射同步更新 downloads 具体文件路径
- [x] DB 更新失败自动删除目标并恢复原源目录
- [x] DB 提交前进程中断自动恢复原源目录
- [x] DB 提交后进程中断保留目标并清理 rollback
- [x] 恢复失败标记 STOP，批处理不继续后续作品
- [x] Journal 路径和所有操作路径必须位于显式 sandbox
- [x] source/target 嵌套、目标占用、symlink、part、空目录和不完整映射 fail-closed
- [x] 将 manifest/映射与执行/恢复拆分为独立模块

### 验收

```text
62/62 external-intake portable tests passed
文件失败注入 rollback passed
DB failure filesystem restore passed
同名目标冲突 passed
部分批次停止 passed
DB 提交前/后崩溃恢复 passed
rollback failure -> STOP passed
Title 层与 downloads 路径一致 passed
真实 E:\arsm / history.db 零访问
```

### 仍然冻结

Tools/CLI 真实执行、quarantine 移动、needs_title_layer 自动命名和正式资源库写入仍未开放。

## TAKEOVER-T4：测试体系与 CI

### 目标

建立一个明确、可重复、默认不接触用户数据的测试入口。

### 任务

- [ ] 增加 `pytest.ini`
- [ ] 新建 `tests/`
- [ ] 把 external intake 测试迁移为 pytest fixture
- [ ] 增加临时 SQLite fixture
- [ ] 增加统一 `python -m pytest` 命令
- [ ] 将真实 Windows 测试标记为 manual/integration
- [ ] 增加 GitHub Actions：syntax + focused unit tests
- [ ] 固定核心依赖版本或增加约束文件

### 验收

```text
Linux/通用环境：纯单元测试通过
Windows：纯单元测试通过
默认测试不读取 E:\arsm 和真实 history.db
```

## TAKEOVER-T5：Windows 本机只读验收

### 负责人

Codex，仅执行必须依赖用户 Windows 本机的部分。

### 任务

1. 确认 git 分支和工作区干净。
2. 运行语法检查与 portable tests。
3. 对真实 `E:\arsm` 运行只读扫描。
4. 对真实 `history.db` 运行只读完整性检查。
5. 输出完整 plan，不执行。
6. 对比 2026-06-28 历史快照，说明变化。
7. 截图核验 UI 扫描、报告和 STOP 提示。

### 验收

```text
不改 DB
不移动文件
不隔离文件
报告完整
UI 不冻结或可接受
```

## TAKEOVER-T6：沙盒执行验收

### 目标

在复制出的临时资源库与临时数据库上验证真实执行流程。

### 任务

- 选取正常、需加 Title 层、需改名、重复 RJ、空目录、part 文件等样本
- 执行完整流程
- 注入文件失败和 DB 失败
- 验证恢复
- 重跑扫描，确保结果幂等

### 验收

```text
第二次 dry-run 无新增动作
数据库与目录一致
失败项可恢复
正常主记录不受重复目录影响
```

## TAKEOVER-T7：真实小批量验收

### 前置条件

T1~T6 全部通过。

### 范围

最多选择 1~3 个无争议作品，只执行目录规范化；重复 RJ、缺文件、part 文件继续人工复核，不在首批执行。

### 验收

- 执行前备份存在
- plan 与实际一致
- DB integrity ok
- 资源库 UI 可打开
- 下载页无异常任务污染
- 回滚信息完整

## TAKEOVER-T8：功能恢复与后续阶段

external intake 通过后再按以下顺序推进：

1. 下载器真实新任务恢复验证
2. metadata_cache 清理/重建决策
3. ToolsView 简化与异步化
4. README/安装运行体验完善
5. 播放器技术验证
6. P7 播放器 MVP

## 当前下一项

```text
TAKEOVER-T4-01：建立 pytest/CI 单一测试门
TAKEOVER-T4-02：锁定依赖并标记 manual/integration tests
TAKEOVER-T4-03：准备 Windows 只读验收说明
```
