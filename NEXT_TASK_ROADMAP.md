# NEXT_TASK_ROADMAP.md

# arsm-downing 接手后详细任务路线图

> 起点：2026-07-18  
> 基线：`main@1f33595`  
> 当前阶段：`TAKEOVER-T1`（`TAKEOVER-T0` 已于 2026-07-20 完成）

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

### 目标

先重写只读扫描与执行计划，不做真实移动和 DB 写入。

### 任务

1. 定义固定 `ExternalIntakePlan` schema：
   - root
   - root_exists
   - scanned_top_dirs
   - unique_rj
   - actions
   - fatal_blockers
   - review_required
   - quarantine_actions
   - warnings
   - can_execute
2. 所有返回路径都使用固定 schema。
3. 明确目录分类：
   - already_normalized
   - needs_title_layer
   - needs_rename_top_level
   - quarantine_candidate
   - duplicate_review
   - fatal
4. 增加 Windows 路径安全检查。
5. 增加目标冲突检查。
6. 报告保存全部 actions，不截断。
7. UI 只展示摘要与前若干项，完整报告写文件。

### 禁止

```text
不移动文件
不修改 history.db
不启动下载 worker
不刷新真实 metadata
```

### 验收

- 临时目录扫描测试通过
- 根目录不存在测试通过
- 重复 RJ 分类测试通过
- 目标冲突测试通过
- 固定 schema 快照测试通过

## TAKEOVER-T2：数据库服务收口

### 目标

external intake 不再直接连接业务 SQLite。

### 任务

1. 在 `LibraryVault` 增加最小查询接口：
   - 获取 RJ 主记录与当前路径
   - 获取 metadata title/tracks
   - 获取 library_items/library_index 路径信息
2. 增加专用写入方法或 service：
   - 更新作品路径
   - 更新 library item 路径
   - 更新 legacy index 路径
3. 写入方法使用统一事务和写锁。
4. 隔离副本不按 RJ 号删除正常主记录。
5. 所有变更生成 preimage/postimage。

### 验收

```text
tools/external_intake.py 不出现业务写入 sqlite3.connect
UI 不创建新的 LibraryVault
重复 RJ 主记录保护测试通过
```

## TAKEOVER-T3：逐作品执行与自动恢复

### 目标

把批量执行拆成可验证、可停止、可恢复的逐作品事务。

### 任务

1. 计划阶段生成逐文件 source/target 映射。
2. 每个作品独立执行。
3. 执行前再次校验计划未漂移。
4. 使用 staging/临时目标。
5. 文件完成后校验数量、大小和关键哈希。
6. 数据库更新失败时恢复文件。
7. 文件恢复失败时立即停止全批次并输出 STOP 报告。
8. 记录每一项：planned / started / moved / db_updated / verified / rolled_back / failed。

### 验收

- 文件移动失败注入测试
- DB 写入失败注入测试
- 同名目标冲突测试
- 部分执行后停止测试
- 自动恢复结果测试

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
TAKEOVER-T0-04：重写 README
TAKEOVER-T0-05：冻结 external intake 执行入口
TAKEOVER-T1-01：定义固定 ExternalIntakePlan schema 和 portable tests
```
