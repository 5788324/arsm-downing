# PROJECT_ROADMAP.md

# ARSM Suite 中长期产品路线

> 更新时间：2026-07-23  
> 当前事实以 `CURRENT_STATE.md` 为准；当前可执行任务以 `NEXT_TASK_ROADMAP.md` 为准。

## 1. 产品方向

ARSM Suite 继续作为一个单体 Windows 个人应用，不拆成多个相互竞争的项目。

```text
ARSM Suite
├─ Downloader：下载、断点、队列和状态
├─ Library：资源库索引、搜索、详情和异常诊断
├─ Maintenance：迁移、External Intake、Tools 和恢复
└─ Player：后续本地播放能力
```

技术主线保持：

```text
Python + Flet + SQLite + asyncio + aiohttp + LibraryVault
```

## 2. 长期不变的原则

### 2.1 SQLite 唯一真源

```text
history.db / SQLite = 业务唯一真源
LibraryVault = 唯一正式数据库访问入口
扫描 JSON / manifest = 报告、缓存或审计证据
```

禁止新增第二套业务数据库来替换当前主线。

### 2.2 不推倒重写

新架构必须通过渐进式门面和只读模型接入：

```text
UI
→ Service / Read Model
→ LibraryVault / Orchestrator
→ SQLite / Network / Filesystem
```

Service 层不是第二个 repository，也不能绕过 `LibraryVault`。

### 2.3 高风险操作独立

以下事项不得与普通 UI 或性能优化混在同一 PR：

- 正式数据库迁移；
- 正式文件移动、隔离或删除；
- External Intake execute；
- VACUUM；
- backlog 批量恢复；
- `.part` 重置；
- 正式目录整理。

## 3. 已完成阶段：基础与 RC

### Phase A：下载器和数据库收口

已完成：

- LibraryVault 单例和 SQLite 访问边界；
- works/downloads 状态诊断与兼容；
- HTTP 200/206/416；
- Range、Content-Range、Content-Length 和 `.part`；
- 暂停、恢复、失败重试与镜像切换；
- metadata cache 受控恢复。

### Phase B：资源库和维护工具

已完成：

- `library_items/library_index`；
- 搜索、分页、封面、异常分类和 Dashboard；
- 快照式 rebuild 和原子索引替换；
- 迁移 manifest、四表同步、回滚和 post-verify；
- External Intake 计划、文件事务、Journal 和沙盒恢复；
- Tools 缓存、队列、VACUUM、backlog 与安全保护。

### Phase C：发布候选

已完成：

- `0.9.0-rc.1`；
- 205 项 portable tests；
- Linux/Windows CI；
- PyInstaller one-folder；
- Windows Artifact 和 SHA-256；
- 隔离路径启动与状态文件边界验证；
- PR #1 合并到 `main`。

当前结果：`PASS_WITH_NOTES`。

## 4. 当前阶段：Post-RC 稳定化

### Phase D1：大队列性能和状态分层

目标：

- 100+ 任务下减少 SQLite N+1 查询；
- 下载页只渲染只读模型；
- 元数据准备和音频下载并发分离；
- 批量 RJ 先预览再统一入队；
- 页面隐藏后停止昂贵刷新；
- 状态迁移显式化。

该阶段只做低风险内部优化，不改数据库 schema，不替换下载核心。

### Phase D2：Windows Desktop 和真实网络证据

目标：

- 用户桌面五页视觉验收；
- 正常关闭、连续启停和残留进程；
- 真实 ASMR.one 认证路径调查；
- 隔离小样本暂停/恢复/完成；
- 长路径、文件占用和 Defender 观察。

视觉证据由具备视觉能力的模型审查，DeepSeek 只负责运行明确脚本，不负责判断截图。

## 5. 后续体验阶段

### Phase E1：资源库体验

候选功能：

- 分类与排序；
- 详情侧栏；
- 文件列表和截断提示；
- 复制路径；
- 最近下载和容量维度；
- 页面生命周期优化。

### Phase E2：托盘与后台运行

候选功能：

- 关闭窗口时退出或最小化到托盘；
- 打开、暂停全部、继续全部、彻底退出；
- 后台状态提示。

该阶段必须建立在当前幂等 shutdown 已稳定的基础上。

### Phase E3：播放器 MVP

候选功能：

- 播放、暂停、上一首、下一首；
- seek 和播放进度；
- 恢复上次位置；
- 常用格式兼容；
- 与资源库详情联动。

播放器不在当前任务中启动。

## 6. 维护窗口阶段

T7 正式小批量目录整理继续冻结。

开放条件：

1. 当前混合任务清空或进入维护窗口；
2. 在线只读 snapshot 和 manifest 通过；
3. 复制资源库沙盒通过；
4. 只选择 1~3 个低风险目录；
5. Journal、rollback 和 post-verify 完整。

该阶段单独立项，不与产品功能开发混合。

## 7. 已放弃 v2 的处理原则

`ARSM Library v2` 作为独立重写分支已放弃。

吸收：

- Service/read model；
- 批量快照；
- 元数据并发池；
- 批量预览；
- 状态迁移；
- 页面生命周期；
- 资源库详情思路；
- 托盘概念。

拒绝：

- 新 `library.db`；
- 新下载表替换现有历史；
- v2 续传实现；
- 不继承旧任务的切换方式；
- 正式库直入开关；
- 未验收的整套 UI 和托盘代码。

## 8. 阶段顺序

```text
已完成：基础下载/资源库/维护/RC
当前：大队列性能与状态分层
随后：Desktop 视觉与真实网络证据
再后：资源库体验与可选托盘
维护窗口：独立执行 T7
最后：播放器 MVP
```

## 9. 成功标准

项目不以功能数量作为成功标准，而以以下结果为准：

- 现有历史和活动任务不丢失；
- `.part` 不被错误删除；
- 数据库状态和真实文件一致；
- 100+ 任务时 UI 仍可用；
- 文件操作有 dry-run、Journal 和恢复路径；
- Windows 构建可重复；
- 文档始终与 `main` 真实状态一致。
