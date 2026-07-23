# ARSM Suite 当前详细任务路线图

> 更新时间：2026-07-23  
> 当前开发版本：`0.9.0-rc.2`  
> 当前生产状态：仍有 100+ 混合状态任务，维护操作继续冻结

## 0. 总原则

```text
不推倒重写
一个任务 = 一个分支 + 一个 PR
批量修改后一个正式提交
不使用真实 E:\arsm 或正式 history.db 作为测试夹具
不把 UI 优化与高风险 DB/文件操作混在一起
不替换当前下载核心和数据库
```

## 1. 已完成里程碑

| 阶段 | 状态 | 结果 |
|---|---|---|
| T0~T4 | PASS | External Intake、事务层、测试和 CI |
| T5A | PASS | 200/206/416、`.part`、暂停恢复 |
| T5C | PASS | 资源库 UI、搜索、分页和后台加载 |
| T6/T6B | PASS | 沙盒执行、Tools、backlog 安全收口 |
| T8A | PASS | 迁移 manifest、四表同步和回滚 |
| T8B | PASS | 快照 rebuild 与原子索引替换 |
| T9 | PASS_WITH_NOTES | 0.9.0-rc.1、Windows 构建与真实下载验收 |
| T9.1 | CODE_COMPLETE | 队列汇总、速度、完成移除、批量按钮和成就页删除 |

## 2. T9.1：下载页现场缺陷修复

### 状态

```text
CODE_COMPLETE / CI_PENDING
```

### 完成内容

- [x] 批量暂停后从 SQLite 刷新队列；
- [x] 批量继续后从 SQLite 刷新队列；
- [x] 修复汇总状态滞后；
- [x] 增加实时全局总网速；
- [x] 卡片显示作品速度；
- [x] 完成作品立即移出活动队列；
- [x] “全部开始”改为“全部继续”；
- [x] 批量按钮按状态启用/禁用；
- [x] 删除“统计与成就”页面；
- [x] 删除成就完成触发；
- [x] 版本升级到 `0.9.0-rc.2`；
- [x] 新增 6 项回归测试。

### 测试

```text
compileall：PASS
portable tests：211/211 PASS
真实 Flet Linux/Windows CI：PENDING
```

### 不在本任务处理

- 10 个输入只形成 9 个不同 RJ 的可视化解释；
- 大队列 N+1 查询；
- metadata queue；
- 页面生命周期；
- 正式数据操作。

这些进入 T10。

---

## 3. TAKEOVER-T10：Queue Service 与大队列性能优化

### 状态

```text
NEXT_AFTER_T9.1_CI
```

### T10-A：下载只读模型

新增：

```text
DownloadQueueItem
DownloadQueueSummary
DownloadTaskDetails
BatchEnqueuePreview
```

状态推导从 Flet View 移到 Service，不持有数据库连接，不执行文件操作。

### T10-B：批量队列快照

在 `LibraryVault` 增加一次性读取：

- work 状态；
- 文件状态汇总；
- 总/已下载字节；
- 文件总数/完成数/失败数；
- 当前文件和错误摘要。

目标：50/100/200 个任务时不再按卡片 N+1 查询，不增加业务表。

### T10-C：轻量 DownloadService

```text
core/services/download_service.py
core/read_models.py
```

Service 只调用现有 `LibraryVault` 和 `Orchestrator`，不成为第二数据库层。

### T10-D：批量 RJ 预览

```text
输入
→ 解析/规范化
→ 只读查重
→ 显示可添加/重复/已完成/已在队列/无效
→ 用户确认
→ 统一入队
```

这项同时解决“提交 10 个但只有 9 个不同 RJ”缺少解释的问题。

查重必须覆盖：

```text
works
downloads
library_items
library_index
RJxxxxxxxx 前缀目录
本次输入内部重复
```

### T10-E：metadata queue 分离

```text
RJ intake
→ metadata queue（默认 2）
→ metadata/tracks/target 完成
→ work download queue
→ file concurrency
```

不改 200/206/416 和 `.part` 逻辑。

### T10-F：页面生命周期

四个页面实现：

```python
def set_active(self, active: bool): ...
```

隐藏页面停止昂贵查询和无意义重绘，后台下载继续。

### T10-G：显式状态迁移

覆盖：

```text
prepared / metadata_failed / queued / downloading / paused
resuming / failed / partial / completed / registered / verified
```

非法迁移默认拒绝、记录日志，不静默覆盖。

### T10 测试要求

- 当前 211 项无回归；
- 批量快照一致性；
- N+1 查询上限；
- 100+ metadata 并发上限；
- 批量预览与去重；
- 页面生命周期；
- 合法/非法状态迁移；
- 临时 SQLite、临时目录和 fake server。

### T10 禁止

```text
不改数据库 schema
不引入 library.db
不替换下载核心
不改 .part 语义
不访问正式数据
不加入托盘
不开发播放器
```

---

## 4. TAKEOVER-T11：Windows Desktop 证据

### 状态

```text
PASS_WITH_NOTES（2026-07-22~23）
```

已验证三次启动/正常关闭、页面打开、设置持久化、真实下载、暂停和恢复。

剩余观察：

- `0.9.0-rc.2` 新导航和下载汇总肉眼复核；
- Defender、极长路径和第三方文件锁。

---

## 5. TAKEOVER-T12：真实 ASMR.one 小样本

### 状态

```text
PASS_WITH_NOTES（隔离 Windows）
```

已验证真实元数据、475 条文件记录、非空 `.part`、暂停/重启/恢复和最终 MP3。

剩余：将认证/token 方式正式写入文档，并确认 10 输入/9 distinct 的原因由 T10 预览明确呈现。

---

## 6. TAKEOVER-T13：资源库体验

```text
BACKLOG
```

- 分类筛选和排序；
- 右侧详情栏；
- 封面、路径、容量和文件统计；
- 最多显示前 200 个文件；
- 打开目录和复制路径。

## 7. TAKEOVER-T14：托盘与后台运行

```text
LATER
```

只吸收概念，不复制 v2 未验收实现。进入开发前必须保证 shutdown、SQLite 和 async loop 不回归。

## 8. T7 与播放器

- T7 正式目录整理继续等待维护窗口；
- 播放器继续延后，排在 T10~T14 之后。
