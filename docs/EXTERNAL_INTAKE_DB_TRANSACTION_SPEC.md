# External Intake 数据库事务规范

> 版本：1.0  
> 日期：2026-07-20  
> 对应阶段：`TAKEOVER-T2`

## 1. 范围

本规范只定义 external intake 的数据库读取与路径引用更新，不定义文件移动、隔离、删除或真实执行开放。

当前约束：

```text
文件系统真实执行：冻结
metadata 在线刷新：冻结
SQLite 读取：仅通过 LibraryVault
SQLite 写入：仅通过 LibraryVault 统一事务
UI：复用 AppController 已存在的 LibraryVault，不创建新实例
```

## 2. 只读快照

`LibraryVault.get_external_intake_snapshot(rj_id)` 返回 JSON 可序列化快照：

- `works` 主记录及 `local_path`
- `metadata_cache` 的 title、metadata 和递归 tracks 原始结构
- `library_items` 路径记录
- `library_index` 所有同 RJ 路径记录
- `downloads` 记录及 pending 数量
- `snapshot_token`

`snapshot_token` 是稳定业务字段的 SHA-256。计划生成后，事务提交前必须重新读取快照并比较 token；不一致时返回 `preimage_changed`，不写数据库。

## 3. 计划中的数据库上下文

`ExternalIntakePlan` schema v2 为每个 action 增加：

```text
db_preimage_token
db_primary_path
db_pending_downloads
db_library_item_paths
db_library_index_paths
```

数据库注释规则：

1. 存在 pending downloads：升级为 `fatal / db_pending_downloads`。
2. `works.local_path` 指向另一份副本：升级为 `duplicate_review / db_primary_path_differs`。
3. `library_items` 指向第三路径：升级为人工复核。
4. `library_index` 同 RJ 存在多条不同路径：升级为人工复核。
5. 任何数据库注释都不会解除执行冻结。

## 4. 路径更新事务

入口：

```text
LibraryVault.update_external_intake_paths(
    rj_id,
    source_path,
    target_path,
    expected_preimage_token=...
)
```

单一 `BEGIN IMMEDIATE` 事务中同步：

- `works.local_path`
- `downloads.local_path`
- `library_items.folder_path / folder_name`
- `library_index.work_dir / library_path`

路径替换按路径组件计算，不使用不安全的 SQL `REPLACE()` 字符串替换。

## 5. 重复 RJ 保护

核心规则：

> 数据库记录不能仅因 RJ 号相同就被修改；记录的当前路径必须与明确的 `source_path` 匹配。

因此：

- 若 `works.local_path` 指向正常主副本，而待处理目录是另一份重复副本，事务返回 `primary_record_protected`。
- 不按 RJ 号删除 `works`、`library_items` 或 `library_index`。
- 同 RJ 的 source/target index 同时存在时返回 `target_reference_conflict`，不自动删除任一记录。
- 目标路径被其他 RJ 占用时返回 `target_owned_by_other_rj`。

## 6. Preimage / Postimage

成功结果必须包含：

```text
preimage
postimage
preimage_token
postimage_token
updated_rows
transaction_id
```

SQLite 中途失败时：

- 整个事务 rollback；
- 所有表恢复原状态；
- 返回 `sqlite_error`；
- 保留提交前 preimage 和 token；
- postimage 为空。

这些数据将在 `TAKEOVER-T3` 与文件操作状态机结合，形成可恢复的逐作品执行日志。

## 7. 当前错误码

| 错误码 | 含义 |
|---|---|
| `read_only_vault` | 只读 Vault 拒绝写入 |
| `invalid_rj_id` | RJ 号为空 |
| `invalid_path` | source/target 为空 |
| `same_path` | source 与 target 等价 |
| `preimage_changed` | 计划后数据库发生变化 |
| `pending_downloads` | 仍有 queued/paused/downloading/failed/resuming |
| `primary_record_protected` | 主记录指向另一份副本 |
| `library_item_path_mismatch` | canonical library item 指向第三路径 |
| `target_reference_conflict` | 同 RJ 的 source/target index 均存在 |
| `target_owned_by_other_rj` | 目标路径属于其他 RJ |
| `no_matching_references` | source 没有匹配数据库引用 |
| `sqlite_error` | SQLite 事务异常并已回滚 |

## 8. 未开放事项

以下仍属于 `TAKEOVER-T3`：

- 文件 source/target 逐项映射
- staging 目录
- 文件复制/移动
- 相对路径、大小、关键哈希校验
- DB 失败后的文件恢复
- 文件恢复失败后的全批次 STOP
- UI 真实执行按钮
