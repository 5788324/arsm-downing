# External Intake 文件事务与恢复规范

> 版本：1.0
> 日期：2026-07-20
> 对应阶段：`TAKEOVER-T3`

## 1. 当前开放边界

本轮只建立 **沙盒执行引擎**：

```text
允许：tempfile / 复制出的临时资源库 / 临时 history.db
禁止：真实 E:\arsm / 正式 history.db / Tools 执行按钮 / CLI --execute
```

生产入口继续硬冻结。`ExternalIntakeSandboxExecutor` 要求 source、target、staging、rollback 和 Journal 全部位于显式 `sandbox_root` 内；任一越界均拒绝。

实现按职责拆分：`core/intake_manifest.py` 负责清单/映射，`core/intake_journal.py` 负责请求与持久化，`core/intake_fs.py` 负责沙盒执行和恢复。

## 2. 计划 schema v3

每个 action 在 schema v2 数据库上下文基础上增加：

```text
source_file_count
source_total_size
source_manifest_token
file_mappings[]
  - source_relative
  - target_relative
  - size
```

`source_manifest_token` 基于相对路径、大小和 `mtime_ns` 生成。执行前重新计算；不一致返回 `source_plan_changed`，不复制文件。

`file_mappings` 是完整逐文件映射。顶层目录改名且已提取 Title 时，源文件会映射到：

```text
RJxxxxxxxx/Title/...
```

数据库中的下载文件路径使用同一映射更新，不能只做目录前缀替换。

## 3. 执行顺序

单作品事务顺序固定：

```text
planned
→ started（重新校验计划和映射）
→ staging copy
→ staged（相对路径、数量、大小、关键哈希通过）
→ source_parked（源目录原子改名为 rollback 目录）
→ target_committed（staging 原子切换为目标目录）
→ verified（目标再次校验）
→ db_updated（LibraryVault 四表事务）
→ completed（删除 rollback 备份）
```

关键设计：

1. staging 位于目标父目录下，和目标处于同一文件系统，最终用 `os.replace()` 切换。
2. rollback 位于源目录父级，源目录暂存使用同文件系统原子改名。
3. 数据库只在目标文件已经完成二次校验后更新。
4. 数据库失败时删除目标并将 rollback 原子恢复为原源目录。
5. 数据库成功后不再擅自反向回滚 DB；若清理 rollback 失败，保留两份数据并标记 `cleanup_pending / STOP`。

## 4. 文件校验

### 计划漂移校验

比较：

- 相对路径
- 文件大小
- 纳秒级修改时间

### staging / target 内容校验

比较：

- 完整相对路径集合
- 文件数量
- 总大小
- 每个文件大小
- 关键文件 SHA-256
- 大文件首尾采样 SHA-256

关键文件至少包括：

- 第一个和最后一个排序文件
- metadata/work JSON
- cover 图片
- 文本、LRC、CUE、常见图片

## 5. Journal

每个事务写独立 JSON Journal，采用临时文件加 `os.replace()` 原子保存。

记录：

```text
transaction_id
source / target / staging / rollback
sandbox_root
preimage token
source manifest
verification manifest
DB result
state/event timeline
error_code/error
stop_required
```

Journal 文件名必须等于 `transaction_id.json`；transaction ID 只允许 8–64 位字母、数字、下划线和连字符，禁止路径穿越。恢复时再次检查所有路径仍位于 sandbox 内。外部或被篡改的 Journal 返回 `unsafe_journal`，不执行文件操作。

## 6. 崩溃恢复

| 崩溃阶段 | 自动恢复 |
|---|---|
| `planned/started/staged` | 删除 staging，保留源目录 |
| `source_parked/target_committed/verified` | 删除目标，rollback 恢复为源目录 |
| `db_updated/cleanup_pending` | 保留已验证目标和 DB 状态，仅删除 rollback 备份 |
| 恢复失败 | `stop_required`，停止后续批次 |

批处理默认在首个失败项后停止。不会跳过失败项继续处理后续作品。

## 7. 强制拒绝条件

- source/target/staging/rollback 任一越出 sandbox
- source 与 target 相同或互相包含
- target 已存在
- source 为空、是 symlink、包含 symlink 或 `.part`
- staging/rollback 残留
- preimage token 或 source manifest token 缺失
- Journal 目录不在 sandbox 内或 transaction ID 非法
- file mapping 不完整、重复、越界或形成文件/子路径冲突
- downloads 文件路径未被显式映射覆盖或指向第三目录树
- action 仍有 review issues
- action 不是当前沙盒允许的 `needs_rename_top_level`

## 8. 当前未开放事项

- Tools 页真实执行按钮
- CLI 批量执行
- 正式资源库执行
- quarantine 候选真实移动
- `needs_title_layer` 自动生成 metadata title
- 新外部作品的 DB 注册/插入事务
- Windows 文件锁、杀毒软件、跨盘权限和长路径实机行为

这些内容必须经过 T4 自动化测试门、T5 Windows 只读验收和 T6 沙盒实机执行后再讨论开放。
