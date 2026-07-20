# TAKEOVER-T8A 迁移模块安全重构与沙盒验收

> 状态：代码级 PASS（2026-07-20）
> 范围：临时目录、临时 SQLite 和复制资源库；不读取或迁移正式资源库。

## 1. 本轮关闭的问题

旧迁移实现存在以下风险：

- 只检查源目录顶层 `.part`，会漏掉嵌套断点文件；
- 空间估算依赖 `works.size_bytes`，可能与磁盘实际大小不同；
- 验证只比较文件总数和总字节，不比较相对路径和逐文件内容；
- 目标目录已存在时可能被直接删除；
- 数据库更新遗漏或弱验证 `library_items`；
- 源目录删除使用 `ignore_errors=True`，失败后仍可能报告成功；
- cleanup plan 只追加，重复执行会累积冲突条目；
- dry-run 在 Flet UI 线程执行，大目录会造成界面冻结。

T8A 已将这些问题收口。

## 2. 新迁移链

```text
读取 completed / verified 候选
→ 拒绝 pending、递归 .part、symlink、路径重叠和已存在目标
→ 构建源目录 manifest
→ 使用磁盘实测文件数和总大小进行空间估算
→ 复制到唯一 staging 目录
→ 按相对路径、逐文件大小和哈希验证 staging
→ 原子提交最终目标
→ 再次验证最终目标
→ 通过统一路径事务更新 SQLite
→ 删除源目录并确认源路径不存在
```

SQLite 路径事务同步：

```text
works.local_path
downloads.local_path
library_items.folder_path / folder_name
library_index.work_dir / library_path
```

## 3. Manifest 规则

`core/migration_manifest.py` 记录每个文件：

- POSIX 形式相对路径；
- 文件大小；
- `mtime_ns`；
- 完整 SHA-256 或大文件首尾采样 SHA-256；
- manifest token。

以下情况拒绝生成计划：

- 源根目录或内部目录/文件为 symlink；
- 任意深度存在 `.part`；
- 目录为空；
- 文件无法读取。

执行时可传入 dry-run 生成的 manifest token。源目录在 dry-run 后发生变化时返回 `source_plan_changed`，不会创建目标目录。

## 4. 失败与回滚语义

### 数据库更新失败

```text
源目录：保持原样
目标目录：删除
数据库：保持 preimage
结果：rollback_performed=true
```

### 源目录删除失败，但源目录仍完整

```text
数据库路径反向恢复到源目录
删除新目标
结果：source_delete_failed_rolled_back
```

### 源目录发生部分删除

无法保证恢复原状态时：

```text
stop_required=true
数据库和完整目标保持在目标路径
保留残余源目录供人工检查
禁止继续后续批次
```

数据库提交后的日志/cleanup plan 等后置步骤发生异常时，也必须标记 `stop_required`，不能静默继续。

## 5. 目标目录保护

迁移不会删除用户已有目标目录。即使目标目录为空，也返回：

```text
target_exists
```

staging 使用唯一随机目录，不复用固定 `.tmp_migrating` 名称。

## 6. 保留源目录模式

默认 UI 模式仍为 `copy_keep_source`。成功后：

- 数据库指向已验证目标；
- 源目录保持不变；
- cleanup plan 按 RJ 原子 upsert，不重复追加；
- cleanup entry 保存 source/target manifest token；
- 后续删除必须再次完成全量验证。

## 7. UI 行为

Tools 页按钮改为：

```text
预览迁移计划
```

其行为是只读 dry-run，不执行文件移动。计划和迁移后验证均通过 worker thread + 独立只读 SQLite 连接运行，避免在 Flet UI 线程执行磁盘哈希和全库验证。

旧 `migrate_execute()` 方法目前没有可见按钮入口；真实迁移继续等待维护窗口。

## 8. 沙盒验收

运行：

```powershell
python scripts/migration_sandbox_acceptance.py `
  --sandbox "D:\ARSM-Acceptance\migration-t8a"
```

脚本仅允许：

- 不存在的新目录；或
- 带 `.arsm-migration-sandbox.json` 且 purpose 正确的既有验收目录。

普通现有目录固定拒绝，不删除其文件。

当前验收项目：

```text
success_completed
source_deleted
target_verified
all_db_paths_target
second_plan_idempotent
nested_part_rejected
db_failure_rolled_back
delete_failure_rolled_back
existing_target_preserved
disk_size_used
```

2026-07-20 本地结果：`10/10 PASS`。

报告：

```text
<migration-t8a>/migration_sandbox_acceptance.json
```

## 9. 仍未开放的范围

以下内容未因 T8A 通过而开放：

- 正式 `history.db`；
- 正式 `E:\arsm` 或当前 Downloads；
- 活跃下载期间的真实迁移；
- Windows 长路径、文件锁、杀毒软件占用；
- 真实批量删除源目录；
- 100+ 混合任务存在期间的维护操作。

真实迁移只能在下载器退出、在线快照完成、目标 RJ 无任何活动/可恢复下载行，并由 Codex 完成 Windows 小批量证据后开始。
