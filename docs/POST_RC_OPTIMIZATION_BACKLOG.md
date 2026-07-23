# Post-RC 优化清单

> 来源：对已放弃 `ARSM Library v2` 的源码审计  
> 目标：只吸收可验证的设计优点，不带入其数据库、下载引擎和兼容问题

## 1. 总体原则

```text
借鉴设计，不复制实现
保留 history.db / LibraryVault
保留当前 200/206/416 下载核心
渐进式接入，不推倒重写
优先解决 100+ 任务的实际性能和可维护性
```

## 2. 吸收矩阵

| v2 设计 | 处理 | 当前主线实现方式 |
|---|---|---|
| UI → Service → Repository | 部分吸收 | UI → Service/read model → LibraryVault/Orchestrator |
| 下载只读模型 | 吸收 | `core/read_models.py` |
| 批量队列快照 | 吸收 | LibraryVault 单次/少量批量查询 |
| metadata/audio 并发池分离 | 吸收 | 独立 metadata queue，不改 file concurrency |
| 批量添加预览 | 吸收 | 全数据源查重后统一确认 |
| 显式状态迁移 | 吸收 | 使用当前项目状态集合重新定义 |
| 页面 set_active | 吸收 | 隐藏页面停止昂贵刷新 |
| 资源库详情侧栏 | 后续吸收 | 保持 SQLite 主数据源 |
| 托盘模式 | 延后 | 重新设计并做 Windows 验收 |
| `library.db` | 拒绝 | 保留 `history.db` |
| `download_tasks/download_files` | 拒绝 | 保留现有 works/downloads |
| v2 下载引擎 | 拒绝 | 当前主线续传更严格 |
| 正式库直入开关 | 拒绝 | 保持现有安全边界 |
| v2 设置保存 | 拒绝 | 保留当前原子配置保存 |
| 整套 v2 UI | 拒绝 | 当前 Flet 版本和页面继续演进 |

## 3. T10-A：Read Models

### 目标

Flet View 不再从多张表和多个对象中自行拼接业务状态。

### 候选模型

```python
@dataclass(frozen=True)
class DownloadQueueItem:
    rj_id: str
    title: str
    work_status: str
    display_status: str
    total_files: int
    completed_files: int
    failed_files: int
    total_bytes: int
    completed_bytes: int
    current_file: str | None
    error_summary: str | None
    can_pause: bool
    can_resume: bool
    can_retry: bool

@dataclass(frozen=True)
class DownloadQueueSummary:
    total: int
    queued: int
    downloading: int
    paused: int
    failed: int
    completed: int
    total_bytes: int
    completed_bytes: int
```

### 规则

- 只读、不可变；
- 不持有 Flet Control；
- 不持有 SQLite connection；
- 不访问文件系统；
- 同样输入必须得到同样输出；
- 显示文案和按钮能力集中计算。

## 4. T10-B：批量队列快照

### 当前问题

下载页在大量卡片场景可能重复读取：

- work；
- downloads；
- metadata；
- 路径；
- 汇总状态。

这会形成 N+1 查询和重复 Python 状态计算。

### 目标接口

```python
LibraryVault.get_download_queue_snapshot(
    *,
    statuses: set[str] | None = None,
    offset: int = 0,
    limit: int = 50,
) -> DownloadQueueSnapshot
```

### 实施建议

- 先按页读取 works；
- 使用 `WHERE rj_id IN (...)` 批量读取 downloads；
- SQL 中完成 count/sum，避免把所有文件记录拉回 UI；
- 当前文件和最近错误使用确定规则选择；
- 保持旧接口供兼容，UI 改完后再评估清理。

### 性能验收

对 10、50、100、200 个任务：

- 查询次数有明确上限；
- 不随卡片数线性增长为多倍查询；
- 快照结果与旧逐任务路径完全一致；
- 页面构建时间和刷新时间记录在测试报告中。

不设置脱离环境的绝对毫秒门槛，优先使用查询次数和相对性能回归。

## 5. T10-C：DownloadService

### 定位

DownloadService 是应用门面，不是新的持久化层。

```text
DownloadView
→ DownloadService
→ LibraryVault + Orchestrator
```

### 职责

- 获取 queue snapshot；
- 生成 read models；
- 批量预览；
- 转发 pause/resume/retry；
- 统一错误和能力判断；
- 保持线程/事件循环边界。

### 禁止

- 自己 `sqlite3.connect()`；
- 自己创建第二个 `LibraryVault()`；
- 缓存业务状态而不失效；
- 直接移动下载文件；
- 绕过 Orchestrator 改下载状态。

## 6. T10-D：批量添加预览

### 输入规范化

接受：

```text
RJ01583845
1583845
https://asmr.one/work/RJ01583845
多行文本
逗号、空格和制表符分隔
```

输出分类：

```text
ready
invalid
duplicate_in_input
already_in_queue
already_in_library
already_completed
needs_review
```

### 查重来源

- works；
- downloads；
- library_items；
- library_index；
- metadata cache；
- output/library roots 的 `RJxxxxxxxx*` 目录。

### 事务边界

预览阶段只读，不创建任务、不写 DB、不发起 metadata 请求。

确认后统一入队，但每个 RJ 仍返回独立结果，单个失败不伪装为全部成功。

## 7. T10-E：Metadata Queue

### 当前目标

限制批量添加时的 metadata 并发，避免 100+ RJ 同时请求。

### 建议模型

```text
metadata_concurrency = 2
work_concurrency = 现有配置
file_concurrency = 现有配置
```

### 状态流

```text
prepared
→ metadata_queued
→ metadata_fetching
→ queued
→ downloading
```

兼容当前状态时，可以先将 metadata 子状态放在内存任务对象和日志中，不必立即新增数据库状态。

### 失败处理

- 认证失败与网络失败分类；
- 401/403 不无限重试；
- 429 尊重 Retry-After；
- 5xx 有限退避；
- metadata 失败不占用 audio 槽；
- 重启后仍以 SQLite/缓存事实恢复，不依赖内存队列真源。

## 8. T10-F：页面生命周期

### 接口

```python
class ViewLifecycle:
    def set_active(self, active: bool) -> None: ...
```

### 下载页

- 激活：开始定时刷新和 UI queue 消费；
- 隐藏：停止卡片重绘；
- 后台下载和数据库写入继续；
- 返回：立即读取一次新快照。

### 资源库页

- 激活：刷新当前查询；
- 隐藏：停止搜索、异常扫描和 summary 重绘；
- rebuild 本身继续运行，但完成结果通过消息队列保留。

### Tools/Dashboard/Settings

- 仅在激活时执行昂贵刷新；
- 设置保存和后台维护状态不因隐藏而丢失。

## 9. T10-G：状态迁移

### 目标

将散落的状态写入收敛为可审查规则。

### 候选迁移

```text
prepared → queued | metadata_failed | paused
queued → downloading | paused | failed
metadata_failed → queued | failed
resuming → queued | downloading | paused | failed
downloading → paused | partial | failed | completed
paused → resuming | queued
partial → resuming | queued | failed | completed
failed → queued | resuming
completed → verified
registered → verified | completed | failed
```

### 兼容原则

旧数据库可能存在历史状态组合：

- 读取时允许归一化；
- 新写入必须遵守规则；
- 非法迁移记录结构化日志；
- 不因规则上线而批量改正式 DB。

## 10. T11：Desktop 视觉证据改进

旧 PowerShell 自动点击方案在路径、压缩层级和窗口自动化上不稳定。

后续优先：

1. 在应用中加入仅开发/验收使用的页面导航参数；
2. 支持启动时打开指定 view；
3. 支持隔离 `--data-dir`；
4. 每个页面单独启动和截图，降低自动点击脆弱性；
5. 使用正常窗口关闭；
6. 机器日志与截图分别打包。

这部分必须单独任务，不混入 T10 性能 PR。

## 11. T12：真实网络与认证

先研究当前程序真实 API 路径，禁止凭空添加 token 逻辑。

需要回答：

- 401 来自哪个端点；
- 浏览器/现有客户端是否使用 cookie；
- API 是否变更；
- 是否存在匿名兼容端点；
- 认证材料的本机存储和日志脱敏方式。

秘密信息不得提交到 Git 或验收包。

## 12. T13：资源库详情

候选 read model：

```text
LibraryAlbumDetails
- rj_id
- title
- cover_path
- canonical_path
- total_size
- audio_count
- subtitle_count
- image_count
- warnings
- first_200_files
- truncated_file_count
```

仍由 `LibraryVault` 返回，不从扫描 JSON 直接读取。

## 13. T14：托盘

托盘开发前检查：

- 当前关闭流程三次连续通过；
- Orchestrator shutdown 幂等；
- SQLite close 幂等；
- asyncio loop 完全退出；
- PyInstaller 包含图标和依赖；
- Windows 10/11 托盘恢复和彻底退出通过。

托盘不是当前优先级。

## 14. 不应吸收的 v2 缺陷

### 续传

不得采用：

```text
Range 非 206 就直接删除 .part
416 先删 .part 再抛错
不验证 Content-Range 起点
不验证最终大小
```

### 目录重复

不得只检查：

```text
root / RJ01583845
```

必须识别：

```text
RJ01583845
RJ01583845 标题
RJ01583845_标题
```

并结合 SQLite 和规范化路径。

### 设置

不得使用直接 `write_text()` 覆盖配置。继续使用临时文件、flush/fsync 和原子替换。

### 正式库边界

不得一边声明只读，一边提供未保护的“直接写入正式库”。

## 15. T10 完成检查表

- [ ] read models 不依赖 Flet/SQLite connection
- [ ] LibraryVault 批量快照完成
- [ ] 查询次数测试完成
- [ ] DownloadService 不成为第二 DB 层
- [ ] 批量预览只读且查重完整
- [ ] metadata 并发有上限
- [ ] 页面隐藏后停止昂贵刷新
- [ ] 状态迁移规则完成
- [ ] 现有 205 tests 无回归
- [ ] 新测试覆盖 100+ 任务
- [ ] 数据库 schema 未变化
- [ ] 下载核心未变化
- [ ] 正式数据零访问
- [ ] README/CURRENT_STATE/WORKLOG/HANDOFF 同步
