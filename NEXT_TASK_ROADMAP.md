# NEXT_TASK_ROADMAP.md

# ARSM Suite 当前详细任务路线图

> 更新时间：2026-07-23  
> 当前基线：`main@9f292e7947804f2e4d53290039501f79c6d1805d`  
> 当前阶段：Post-RC 稳定化  
> 当前生产状态：仍有 100+ 混合状态任务，正式维护操作继续冻结

## 0. 总原则

```text
不推倒重写
一个任务 = 一个分支 + 一个 PR
批量修改后一个正式提交
不在 main 直接开发
不使用真实 E:\arsm 或正式 history.db 作为测试夹具
不把低风险 UI 优化与高风险 DB/文件操作混在同一任务
不因已放弃 v2 而替换现有数据库或下载核心
```

## 1. 已完成里程碑

| 阶段 | 状态 | 结果 |
|---|---|---|
| T0~T4 | PASS | External Intake 冻结、计划模型、事务层、统一测试和 CI |
| T5A | PASS | HTTP 200/206/416、`.part`、暂停恢复、镜像切换 |
| T5C | PASS | 资源库搜索、分页、异常视图和后台加载 |
| T6/T6B | PASS | 复制资源库沙盒、Tools、backlog 安全收口 |
| T8A | PASS | 迁移 manifest、四表同步、回滚和 post-verify |
| T8B | PASS | 快照式资源库 rebuild 与原子索引替换 |
| T9 | PASS_WITH_NOTES | 0.9.0-rc.1、构建链、Windows Artifact 和隔离启动 |

PR #1 已合并到 `main`。当前路线图不再保留“等待 PR #1 合并”的旧任务。

---

## 2. TAKEOVER-T10：Queue Service 与大队列性能优化

### 状态

```text
NEXT
```

### 目标

吸收已放弃 ARSM Library v2 中最有价值的架构思想，在不改数据库 schema、不替换下载核心的前提下，优化 100+ 任务场景下的查询、状态组装和 UI 刷新。

### 范围

#### T10-A：下载只读模型

新增轻量只读模型，例如：

```text
DownloadQueueItem
DownloadQueueSummary
DownloadTaskDetails
BatchEnqueuePreview
```

要求：

- 模型只承载 UI 所需字段；
- 不持有 SQLite 连接；
- 不在模型中执行文件操作；
- 状态推导集中在 Service 层，不继续散落在 Flet View。

#### T10-B：批量队列快照

在 `LibraryVault` 增加批量读取接口，一次返回当前页面所需的：

```text
work 状态
下载文件汇总
总字节数/已完成字节数
总文件数/完成数/失败数
当前文件
错误摘要
```

验收目标：

- 50/100/200 个任务时不按卡片逐个查询；
- 查询次数保持常数级或按页数增长；
- 结果与原逐任务读取一致；
- 不增加新业务表。

#### T10-C：Service 门面

新增轻量服务层：

```text
core/services/download_service.py
core/read_models.py
```

职责：

- 组装下载队列只读模型；
- 统一状态文案和进度计算；
- 批量添加预览；
- 调用现有 `LibraryVault` 和 `Orchestrator`；
- 不成为第二个数据库访问层。

#### T10-D：批量 RJ 预览

流程改为：

```text
粘贴 RJ 列表
→ 解析和规范化
→ 只读查重
→ 展示可添加/无效/重复/已完成/已在队列
→ 用户确认
→ 统一入队
```

查重必须同时考虑：

- `works`；
- `downloads`；
- `library_items`；
- `library_index`；
- 以 `RJxxxxxxxx` 为前缀的真实目录。

不得复制 v2 只检查 `inbox/RJ号` 的缺陷。

#### T10-E：元数据队列分离

现有下载文件并发保持不变，新增独立 metadata queue：

```text
RJ intake
→ metadata queue（默认 2）
→ metadata/tracks/target 准备完成
→ work download queue
→ file concurrency
```

要求：

- 100+ RJ 入队时不一次性创建无上限 metadata 请求；
- metadata 失败不占用音频下载槽；
- 暂停、恢复和重启恢复语义不倒退；
- 不修改 200/206/416 下载响应计划。

#### T10-F：页面生命周期

所有主要页面增加：

```python
def set_active(self, active: bool): ...
```

行为：

- 当前页允许刷新；
- 隐藏页停止定时重绘和昂贵查询；
- 后台下载、队列和数据库事务继续运行；
- 切回页面时主动刷新一次。

#### T10-G：状态迁移规则

建立当前项目自己的显式状态迁移，不照搬 v2 枚举。

至少覆盖：

```text
prepared
metadata_failed
queued
downloading
paused
resuming
failed
partial
completed
registered
verified
```

非法迁移：

- 默认拒绝；
- 写入日志；
- 不静默覆盖；
- 对兼容旧数据保留受控归一化入口。

### 禁止事项

```text
不改现有表结构
不引入新的 library.db
不导入 v2 download_tasks/download_files
不替换 core/network.py 的续传核心
不修改正式任务
不访问真实 E:\arsm
不加入托盘
不开发播放器
```

### 测试要求

- 现有 205 项测试全部通过；
- 新增批量快照一致性测试；
- 新增查询次数/调用次数上限测试；
- 新增 100+ RJ metadata queue 并发测试；
- 新增批量预览查重测试；
- 新增页面生命周期测试；
- 新增合法/非法状态迁移测试；
- 使用临时 SQLite、临时目录和本地 fake server。

### 完成标准

```text
PASS：
- 旧行为无回归
- 100+ 任务页面不再 N+1 查询
- metadata 并发有上限
- UI 不再自行推导复杂状态
- 数据库 schema 未变化
- 下载核心未变化
- 正式数据零访问
```

---

## 3. TAKEOVER-T11：Windows Desktop 视觉与交互证据

### 状态

```text
PENDING_AFTER_T10 或独立并行
```

### 目标

补齐 `PASS_WITH_NOTES` 中的 Flet Desktop 现场证据。

### 方法

由于 DeepSeek 没有视觉能力，后续不再让其自行判断截图。优先采用：

1. 程序内部增加低风险的“验收模式”或页面截图辅助；
2. 用户只负责打开隔离便携包并逐页截图；
3. 截图上传给 ChatGPT，由具备视觉能力的模型审查；
4. 进程、日志和关闭结果由机器脚本记录；
5. 视觉结论与机器结论分开。

### 验收页面

```text
下载中心
资源库
统计与成就
系统工具
设置
```

检查：

- 黑屏、白屏、加载不结束；
- 中文乱码；
- 控件重叠和截断；
- 窗口缩放、最小化、恢复；
- 正常关闭后无残留进程；
- 连续三次启动/关闭。

### 边界

- 使用隔离目录；
- 不复制正式配置和数据库；
- 不使用 `Kill()` 冒充正常关闭；
- 没有截图的页面不得标记 PASS。

---

## 4. TAKEOVER-T12：真实 ASMR.one 网络小样本

### 状态

```text
PENDING
```

### 目标

在隔离目录验证真实站点的小作品下载。

### 前置调查

此前 API 返回 401，因此先确认：

- 当前公开 API 是否仍可匿名访问；
- 是否需要 cookie/token；
- 当前程序实际使用的端点和认证方式；
- 密钥如何只保存在本机配置，不进入 Git、日志或报告。

### 验收

- 获取真实 metadata；
- 获取封面和递归 tracks；
- 开始下载；
- 暂停后保留 `.part`；
- 恢复后 Range 正确；
- 最终文件大小和 SHA-256 合理；
- `history.db` 仅包含隔离任务；
- 正式目录和正式队列不变。

没有有效认证环境时，结论只能是 `BLOCKED_BY_AUTH`，不能用 401 代替 PASS。

---

## 5. TAKEOVER-T13：资源库体验优化

### 状态

```text
BACKLOG
```

### 可吸收内容

- 分类筛选；
- RJ/标题/容量/音频数量/最近下载排序；
- 右侧详情栏；
- 封面、路径、容量、文件统计；
- 最多展示前 200 个文件并明确截断；
- 打开目录和复制路径；
- 页面离开后停止后台搜索和统计刷新。

### 边界

- 数据仍来自 `LibraryVault / SQLite`；
- 不读取扫描 JSON 作为 UI 主源；
- 不新增第二套资源库数据库；
- 不在本任务中移动或整理文件。

---

## 6. TAKEOVER-T14：托盘与后台运行

### 状态

```text
LATER
```

仅吸收概念，不复制 v2 未验收的 pystray 实现。

候选设置：

```text
关闭窗口时：
- 退出程序
- 最小化到系统托盘
```

托盘菜单候选：

- 打开 ARSM Suite；
- 暂停全部；
- 继续全部；
- 彻底退出。

进入开发前必须先保证当前幂等 shutdown、SQLite 关闭和 async loop 退出不回归。

---

## 7. TAKEOVER-T7：维护窗口小批量正式验收

### 状态

```text
FROZEN
```

该任务与 T10~T14 分开，不因 UI 优化自动开放。

前置条件：

1. 现有混合任务自然清空或明确暂停；
2. 在线只读 snapshot 与 manifest 通过；
3. 复制资源库沙盒再次通过；
4. 选择 1~3 个无 `.part`、无 symlink、无重复 RJ 的低风险目录；
5. 有明确回滚目录和 Journal。

正式执行仍需单独任务、单独分支和单独验收。

---

## 8. 播放器阶段

### 状态

```text
DEFERRED
```

只有在以下条件满足后再开始：

- T10 大队列优化稳定；
- T11 桌面视觉通过；
- T12 真实下载通过或明确长期替代方案；
- 当前维护冻结边界稳定；
- 没有高优先级下载/数据库缺陷。

播放器 MVP 再单独设计，不与下载队列优化混合。

---

## 9. 当前执行顺序

```text
T10 Queue Service 与大队列性能
→ T11 Desktop 视觉证据
→ T12 真实网络小样本
→ T13 资源库体验
→ T14 可选托盘
→ 维护窗口开放时单独执行 T7
→ 最后评估播放器
```

## 10. 当前最重要的一句话

```text
当前主线已经完成 RC 合并；下一轮只吸收 v2 的低风险设计优点，先解决 100+ 任务的查询、并发和 UI 状态分层，不带入其数据库、下载引擎和兼容性问题。
```
