# Tools 维护操作安全约束

> 更新时间：2026-07-20

Tools 页的数据库与队列维护不能在活跃下载期间做“顺手清理”。当前实现遵守以下规则。

## 队列清理

当前只提供只读预览：

- 统计 SQLite 中的终态记录；
- 统计 `queue.json` 中的终态项；
- 发现 queued/paused/downloading/resuming/failed/stale/ignored 时标记 blocked；
- 不执行 `DELETE FROM downloads`；
- 不改写 `queue.json`；
- 不顺带执行 VACUUM。

## 元数据缓存

只删除超过 TTL 且没有被可恢复任务引用的缓存。

以下状态引用的旧缓存必须保留：

```text
queued
paused
downloading
resuming
failed
stale
ignored
```

删除采用两阶段校验：

```text
只读 preview + token
→ BEGIN IMMEDIATE
→ 再次检查任务引用
→ 删除精确候选
```

preview 变化时不删除。

## VACUUM

VACUUM 使用独立 SQLite 连接并放到后台线程。只要存在任何活动或可恢复下载记录，就返回 blocked，不修改数据库。

## 历史任务恢复

- 预览为只读；
- 不再硬编码排除某个 RJ；
- UI 和 CLI 都要求运行时队列完全空闲；
- 默认 `continue`，保留 `downloaded_bytes` 和 `.part`；
- `retry-from-zero` 遇到 `.part` 时固定拒绝；
- 执行前生成 SQLite online backup、preimage 和 rollback SQL；
- 只把 stale/ignored 改为 queued；completed 和 works 必须保持不变；
- 加锁后再次核对队列状态和 preimage，发现变化则不更新。

## 系统诊断

诊断只读打开数据库，并检查已有输出目录是否存在/可写。它不得为了“测试权限”创建目录，也不得修改配置或 SQLite。

## 失败任务诊断与 backlog 统计

两者均使用独立只读 SQLite 连接，并由 worker thread 执行文件存在性检查。Flet 线程只接收不可变结果并渲染，避免大量 `.part`/final 路径检查造成窗口卡顿。
