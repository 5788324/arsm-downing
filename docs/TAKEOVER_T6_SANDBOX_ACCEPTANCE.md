# TAKEOVER-T6 复制资源库沙盒验收

> 状态：代码级 PASS（2026-07-20）
> 范围：一次性临时目录与临时 SQLite；不连接正式下载器和正式资源库。

## 1. 目的

验证 External Intake 文件事务在真实目录复制、原子切换、数据库更新、故障回滚和二次扫描时保持一致，而不是只依赖 mock 或源码检查。

该验收不等同于 Windows 正式资源库验收。以下内容仍保持冻结：

```text
Tools / CLI 真实执行入口
E:\arsm 或其他正式资源库
活跃 history.db
quarantine 批量移动
needs_title_layer 自动命名
```

## 2. 运行方式

建议使用一个不存在的新目录：

```powershell
python scripts/intake_sandbox_acceptance.py `
  --sandbox "D:\ARSM-Acceptance\intake-t6"
```

不指定目录时，脚本使用 `TemporaryDirectory` 并自动清理：

```powershell
python scripts/intake_sandbox_acceptance.py
```

## 3. 目录删除保护

脚本不得把任意现有目录视为可清空的 sandbox。

首次创建时会写入：

```text
.arsm-intake-sandbox.json
```

再次使用同一路径前必须同时满足：

- 标记文件存在；
- `purpose` 精确等于 `arsm-intake-acceptance`；
- 路径不是磁盘根目录、用户主目录或仓库根目录。

现有目录没有正确标记时，脚本直接失败，不删除其中任何文件。

## 4. 固定样本

| 样本 | 预期 |
|---|---|
| `RJ01010001 Rename Sample` | 执行改名，并把文件放入 Title 层 |
| `RJ01010002` 根目录直接有文件 | `needs_title_layer`，只允许人工复核 |
| `RJ01010003 Copy A/B` | `duplicate_review`，数据库主记录保持不变 |
| `RJ01010004` 空目录 | `quarantine_candidate` |
| `RJ01010005` 含 `.part` | `quarantine_candidate` |
| `RJ01010009/Normalized Title` | `already_normalized` |
| `RJ01010006 Database Failure` | 注入 DB 失败，文件和数据库整体回滚 |
| `RJ01010007 Cleanup Failure` | DB 提交后注入清理失败，再按 Journal 恢复 |

## 5. 实际执行链

```text
扫描与 DB 上下文标注
→ 生成 file_mappings / manifest token
→ staging 复制
→ staging 校验
→ source 停放到 rollback
→ target 原子提交
→ target 再校验
→ 四表数据库事务
→ rollback 清理
→ 第二次扫描验证幂等
```

## 6. 验收结果

当前自动验收包含 11 个结果断言：

```text
rename_completed
mapped_file_exists
db_matches_target
second_scan_idempotent
title_layer_requires_review
duplicate_requires_review
empty_is_quarantine
part_is_quarantine
database_failure_rolled_back
cleanup_failure_recovered
duplicate_primary_unchanged
```

2026-07-20 本地结果：`11/11 PASS`。

报告文件：

```text
<intake-t6>/intake_sandbox_acceptance.json
```

## 7. T7 前置门槛

真实小批量验收只有在以下条件全部满足时才允许开始：

- T6 报告 PASS；
- Windows 文件锁、长路径和杀毒软件影响已经观察；
- 目标 RJ 没有 queued/downloading/resuming/paused/failed 行；
- 当前下载器完全退出或明确进入维护窗口；
- 仅选择 1–3 个无重复、无 `.part`、无人工复核项的作品。

用户当前仍有 100 多个混合状态下载任务，因此 T7 暂不执行。
