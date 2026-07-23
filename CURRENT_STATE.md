# ARSM Suite 当前状态

> 更新时间：2026-07-23  
> 已发布候选：`0.9.0-rc.1`  
> 当前开发候选：`0.9.0-rc.2`  
> 当前阶段：下载页现场缺陷修复，随后进入 TAKEOVER-T10

## 1. 当前产品状态

ARSM Suite 继续作为一个单体 Windows Flet 应用，当前主页面为：

```text
下载中心
资源库
系统工具
设置
```

“统计与成就”页面已从 `0.9.0-rc.2` 删除。历史配置中的 `achievements` 字段暂时保留兼容读取，不再展示或写入新成就。

## 2. 架构约束

```text
history.db / SQLite = 唯一业务真源
LibraryVault = 唯一正式数据库访问入口
UI 不直接 sqlite3.connect()
queue.json 不作为历史状态真源
文件移动/隔离/删除必须 dry-run 且可恢复
```

## 3. 已完成阶段

| 阶段 | 状态 | 结果 |
|---|---|---|
| T0~T4 | PASS | External Intake 冻结、事务层、统一测试和 CI |
| T5A | PASS | 200/206/416、`.part`、暂停恢复和镜像切换 |
| T5C | PASS | 资源库搜索、分页、异常视图和后台加载 |
| T6/T6B | PASS | 复制资源库沙盒、Tools 与 backlog 安全收口 |
| T8A | PASS | 迁移 manifest、四表同步和回滚 |
| T8B | PASS | 快照 rebuild 与原子索引替换 |
| T9 | PASS_WITH_NOTES | 0.9.0-rc.1、构建链和 Windows Artifact |
| T9.1 | CODE_COMPLETE | 下载页现场缺陷修复与成就页删除 |

## 4. 0.9.0-rc.1 发布与 CI

```text
PR #1：MERGED
main 合并提交：9f292e7947804f2e4d53290039501f79c6d1805d
portable pytest：205/205 PASS
Ubuntu / Python 3.10：PASS
Windows / Python 3.12：PASS
Windows one-folder Artifact：PASS
```

## 5. Windows 11 真实验收

Codex 隔离验收记录：

```text
Windows 11 Pro 10.0.26200 x64
main/tag SHA：9f292e7947804f2e4d53290039501f79c6d1805d
结论：PASS_WITH_NOTES
```

已经实际验证：

- 连续三次启动并通过标题栏正常关闭；
- 下载中心、资源库、统计与成就、系统工具、设置均能打开（成就页现已决定删除）；
- 隔离配置原子保存并在重启后保留；
- 真实元数据和文件列表写入；
- 9 个不同 RJ、475 条下载记录；
- 暂停后 466 条 paused，非空 `.part` 保留；
- 正常关闭、重启后暂停状态保持；
- “全部开始”能够恢复下载；
- `.part` 数量和字节数继续增长；
- 存在 14,017,924 字节的最终 MP3；
- 未触碰正式 DB、正式目录和正式任务。

确认的缺陷：

```text
批量恢复后，底部汇总仍显示旧的“下载中 0、排队 0、暂停 9”。
```

## 6. T9.1 修复内容

`0.9.0-rc.2` 已完成代码级修复：

1. 批量暂停/继续完成后发送一次 UI 刷新消息；
2. 下载页从 SQLite 重新构建活动队列；
3. 汇总文本与按钮状态同步刷新；
4. 汇总显示实时全局总速度；
5. 每张卡使用 `work_speed_bps`，不再把全局速度复制到每张卡；
6. 工作完成后立即从活动队列移除；
7. “全部开始”改名为“全部继续”；
8. 没有可暂停/继续任务时按钮自动禁用；
9. 删除 Dashboard/统计与成就页面；
10. 删除下载完成后的成就检查调用。

本地验证：

```text
compileall：PASS
portable tests：211/211 PASS
```

待 GitHub 使用真实 Flet 0.27.6 运行 Linux/Windows CI。

## 7. 批量按钮结论

两个按钮都有实际核心作用：

- **全部暂停**：把 queued/downloading 文件写为 paused、冻结速度、清空内存队列并取消活动任务；
- **全部继续**：清除 global pause，扫描可恢复任务，重新准备目标并入队。

此前“像没用”的主要原因是 UI 汇总不刷新，不是核心动作没有执行。

## 8. 尚待确认

Windows 验收提交了 10 个任务，但 SQLite 中是 9 个不同 RJ。当前没有证据证明数据丢失；可能是输入重复、已存在任务或无效项被去重。该问题进入 T10 的批量预览功能：提交前明确显示可添加、重复、已存在和无效数量。

## 9. 正式环境边界

本轮开发和测试均未：

- 连接或修改正式 `history.db`；
- 读取、移动或删除真实 `E:\arsm`；
- 修改正式配置或队列；
- 改动现有 100+ 混合状态任务；
- 修改 200/206/416 下载核心或 `.part` 语义。

## 10. 当前冻结

```text
External Intake execute
正式资源库迁移、移动、隔离和删除
正式 VACUUM
正式 backlog execute
T7 正式目录整理
```

## 11. 下一步

1. 推送 T9.1 单独分支和 PR；
2. GitHub Linux/Windows CI 使用真实 Flet 运行；
3. CI 通过后合并 `0.9.0-rc.2` 修复；
4. 开始 `TAKEOVER-T10：Queue Service 与大队列性能优化`。
