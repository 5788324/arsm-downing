# TAKEOVER-T8B：资源库快照重建

> 完成日期：2026-07-20
> 范围：临时目录、临时 SQLite、后台 UI 调用

## 实现

- 文件系统扫描与 SQLite 写入分离：先生成完整 `LibraryScanSnapshot`，成功后再提交。
- `library_index` 保存全部发现目录；`library_items` 每个 RJ 选择一个卡片主路径。
- 重复 RJ 优先沿用 `works.local_path` / 旧 `library_items.folder_path`，并记录 `duplicate_rj`。
- `library_items` 与 `library_index` 在同一个 SQLite 事务中整体替换，陈旧行自动清理。
- 新发现作品写入 `works(status=external)`；外部/索引类旧记录同步路径与容量。
- queued、paused、failed、downloading、resuming 对应作品的 `works` 主路径不改动。
- 扫描失败、目录在扫描后消失或 SQLite 写入失败时，旧索引保持不变。
- metadata 音轨验证支持任意层级 folder/children 嵌套。
- Tools 页“扫描仓库”改为后台快照重建，并显示新增、更新、陈旧清理和缺失统计。

## 自动验证

```text
pytest：183/183 passed
T8B 沙盒验收：10/10 checks PASS
ResourceWarning 严格模式：PASS
compileall：PASS
git diff --check：PASS
```

## 现场边界

本轮未读取或修改正式 `history.db`、`queue.json`、下载目录或 `E:\arsm`。现有 100+ 混合下载任务不受影响。
