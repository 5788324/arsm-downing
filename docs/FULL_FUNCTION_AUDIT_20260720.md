# arsm-downing 全功能代码审查

> 修复状态：TAKEOVER-T0~T5A 与 T5C 已完成 external intake 安全收口、统一 pytest 门、活跃 DB 在线快照，以及下载 200/206/416、断点进度和主要 UI 控制语义修复；真实 external intake 与 Windows live/UI 验收仍冻结或待执行。

> 日期：2026-07-20  
> 审查基线：`chatgpt/takeover-20260718@7bacbf4`  
> 范围：启动与生命周期、配置、网络、下载、暂停/恢复、SQLite、资源库、统计、迁移、外部资源整理、历史任务恢复、音频标签、工具页、测试与 CI。

## 结论

项目已有较完整的功能基础，不需要推倒重写，但当前不能直接视为稳定版本。

主要问题不是功能数量不足，而是：

- 高风险文件/数据库操作缺少统一事务与恢复闭环；
- 若干 UI 按钮与实际核心行为不一致；
- 下载断点续传存在错误完成判断风险；
- 资源库验证可能把嵌套目录中的缺失音轨误判为已验证；
- 新数据库缺少 `library_items` 建表闭环；
- 历史测试数量很多且质量不一；现已建立 138 项可信 portable pytest 门，但 200 个旧脚本尚未全部迁移。

## P0：可能造成数据损坏、错误完成或不可恢复状态

### P0-01 External intake 旧执行入口仍可写真实文件与数据库

- UI 仍保留“执行整理”。
- 旧实现直接移动/隔离目录并直接写 SQLite。
- 重复 RJ 的隔离路径可能删除正常主记录。
- 文件系统与数据库更新没有可靠原子恢复。

处理状态（2026-07-20）：旧执行体已删除，核心/CLI/UI 已硬冻结；计划 schema v3 已接入 LibraryVault 快照、逐文件映射和 source manifest；四表事务、staging、关键哈希、Journal、DB 失败回滚与崩溃恢复已在 tempfile 沙盒通过。真实 Tools/CLI/正式资源库执行继续冻结。

### P0-02 下载断点续传的 HTTP 416 处理不可信

- HTTP 416 当前可直接标记 `completed`，未校验最终文件或 `.part` 文件是否真的等于目标大小。
- 响应处理 `finally` 可能在 `target` 尚未赋值时引用它。
- 取消时写回的 `downloaded_bytes` 可能是旧值，而不是当前 `.part` 实际大小。

处理状态（2026-07-20）：已抽离纯响应计划；200/206/416 均校验本地大小、Range 和响应长度；取消/失败从磁盘读取真实 `.part`；本地 aiohttp 200/206/416 集成通过。真实 ASMR.one 与 Windows 仍待 T5B。

### P0-03 资源库完整性校验不递归

`verify_library_item()` 遇到 metadata folder 仅跳过 folder 本身，没有递归验证 children，可能将嵌套音轨缺失的作品标记为 `verified`。

处理：复用统一的递归 track flatten，并按相对路径或可解释匹配规则验证。

### P0-04 迁移后数据库视图不完整

迁移只更新：

- `works.local_path`
- `downloads.local_path`
- `library_index`

未更新/重建 `library_items`，资源库卡片仍可能指向旧路径；迁移验证也没有检查 `library_items`。

处理状态（2026-07-20）：`move_work_to_path()` 已委托统一路径事务，同步 `works`、`downloads`、`library_items`、`library_index` 并返回 pre/postimage。迁移层 post-verify 对 `library_items` 的显式核验仍待后续补充。

### P0-05 迁移可能漏检嵌套 `.part`

`_has_part_files()` 只扫描源目录顶层。子目录中的 `.part` 不会阻止迁移。

处理：改为递归扫描；测试顶层与多层嵌套。

### P0-06 新数据库缺少完整 schema

`LibraryVault._init_schema()` 创建 `works`、`metadata_cache`、`downloads`、`library_index`，但资源库 UI 直接查询 `library_items`。全新安装或新数据库可能出现资源库/统计为空或查询错误。

处理状态（2026-07-20）：全新数据库已创建 `library_items` 基础 schema 与 `scan_run_id` 索引，并对旧表补列。正式 schema version 表和完整迁移框架仍待 DATA-CORE 阶段。

## P1：主要功能错误或高概率 UI/状态异常

### P1-01 Flet UI 跨线程更新混用

项目已经建立 UI 消息队列，但部分后台协程仍直接调用控件更新、SnackBar、日志 ListView 和队列刷新。可能产生偶发 UI 冻结、更新丢失或关闭异常。

处理状态（2026-07-20）：下载准备、恢复、重连、批量控制和关闭回调已统一经过后台 loop/UI queue；LibraryView 的 DB/文件系统读取已转 worker thread 并经 UI callback 返回。ToolsView 其他长操作仍需继续审查。

### P1-02 设置页并发滑块无效

设置页保存 `max_concurrent`，实际下载器使用 `work_concurrency` 和 `file_concurrency`。用户修改“最大并发下载数”不会改变真实下载行为。

处理状态（2026-07-20）：已拆为 work/file concurrency 并保存真实字段，UI 明确重启生效；动态调整仍不在当前范围。

### P1-03 下载页按钮语义与行为不一致

- “仍然下载/强制下载”未传 `allow_duplicate=True`，仍会被核心重复检查拦截。
- “取消下载”实际调用 pause，只隐藏卡片，DB 中暂停记录仍保留。
- “打开目录”按当前模板重新拼路径，不读取数据库真实 `local_path`，迁移后可能打开错误目录。
- “重连”同时调度 pause/resume，存在竞态。
- 暂停/失败任务读取的 queue.json tracks 随后被丢弃。
- 批量恢复混合列表中仍会遍历 failed-only 项。

处理状态（2026-07-20）：强制重复、canonical directory、顺序重连、队列 tracks 恢复和批量线程路径已修；当前“取消”明确标注为保留断点的暂停并隐藏。永久移除仍需独立产品语义。

### P1-04 资源库搜索失效

搜索框会触发刷新，但卡片查询和计数未传入 search 参数；异常视图也没有应用搜索词。

处理状态（2026-07-20）：已统一 query state；卡片 SQLite 查询和异常分类均应用 RJ/标题/路径搜索。非空搜索改为回车/按钮触发，避免每次按键全库扫描。

### P1-05 资源库和工具页硬编码本机状态

- `E:\arsm`
- 旧用户路径
- 特定假 RJ/别名 RJ
- `磁盘扫描: ~227`
- backlog 排除特定 RJ

处理状态（2026-07-20）：LibraryView 已删除 E 盘、用户目录、固定 227、假 RJ/别名 RJ；异常分类改用 output_dir/library_paths。ToolsView 的 backlog 特定 RJ 排除等历史硬编码仍待处理。

### P1-06 工具页存在阻塞和假功能

- 仓库扫描、VACUUM、队列清理在 UI 线程同步执行。
- 后台 enrich/verify 直接写 UI 日志。
- “清理元数据缓存”仅 sleep 0.5 秒并报告成功，没有清理任何数据。
- 清理队列后又执行一次 VACUUM。
- “迁移已完成作品”当前只执行 dry-run，真实 execute 方法没有对应可见入口。

处理：重任务进入后台服务；假功能删除或实现；危险动作显示明确阶段与结果。

### P1-07 资源库扫描与索引重建不可靠

- 扫描深度固定为两层。
- 文件统计异常处理不足。
- 旧 `library_index` 记录没有在同一轮扫描中可靠标记/清理。
- `rebuild_library()` 会读取所有历史 index 行，可能重新插入已失效作品。

处理：引入 scan_run_id 或 staging table，扫描完成后原子切换当前快照。

### P1-08 7 天缓存过期会阻止暂停任务恢复

恢复下载调用普通 `get_metadata_cache()`；缓存超过 7 天会返回 None，即使数据库仍保存完整 metadata/tracks。

处理：在线获取使用 TTL，离线恢复允许读取 stale cache，并标记来源。

### P1-09 backlog 恢复工具的备份与回滚不可信

- WAL/SHM 备份路径拼接为 `history.db.db-wal`/`history.db.db-shm`。
- rollback SQL 对 NULL 和字符串转义不可靠。
- UI 调用 execute 时强制绕过批量限制。
- retry-from-zero 只清 DB 字节数，不删除 `.part`，实际可能继续断点。

处理：通过 SQLite backup API + 参数化 preimage restore；真正的 retry-from-zero 同步处理临时文件。

### P1-10 迁移完成判定偏弱

- copy verify 只比较总文件数和总字节数，不逐相对路径比较。
- 删除源目录使用 `ignore_errors=True`，即使删除失败也可能返回 success。
- 迁移空间估算使用 DB `size_bytes`，可能低于磁盘真实大小。

处理：逐相对路径+大小清单验证；删除后确认源不存在/为空；空间估算来自实时扫描。

## P2：质量、兼容性和可维护性

### P2-01 音频标签支持不完整

- MP3/FLAC 封面 MIME 固定声明 JPEG，即使实际为 PNG/WebP。
- OGG 不写封面。
- M4A/AAC/Opus/WMA 下载后不写标签。
- EasyID3 自定义键需要显式注册或换用标准帧并增加实测。

### P2-02 网络镜像缺少自动故障转移

配置包含多个 API mirror，但运行时只使用当前单一 mirror。当前镜像失败不会自动切换。

### P2-03 配置缺少验证

未充分验证：输出目录为空/不可写、library_paths 与 output_dir 冲突、代理 URL 格式、并发范围、目录模板字段。

### P2-04 依赖和测试门禁不足

处理状态（2026-07-20）：

- runtime/dev 核心依赖已精确锁定；Flet 保持当前 legacy API 兼容的 0.27.6；
- 已建立 `pytest.ini`、125 项 portable tests、Linux/Windows GitHub Actions 定义；
- 默认 gate 发现 live `history.db/config.json/queue.json` 时 fail-closed；
- 已增加活跃 SQLite online backup、integrity_check、SHA-256 manifest 和混合状态报告；
- 200 个 `scripts/test_*.py` 尚未全部迁移，仍不能把历史脚本数量等同于覆盖率；
- GitHub Actions 尚待最终推送后由远端 Runner 真实验证。

## 功能域结论

| 功能域 | 结论 |
|---|---|
| 启动/关闭 | 可用基础存在；线程关闭与 UI 回调需收口 |
| 配置/设置 | work/file concurrency 已修；代理、模板和路径完整验证仍待加强 |
| 网络/代理 | 三通道代理与有限镜像切换已实现；真实代理/镜像仍需 Windows 验收 |
| 元数据 | 新鲜 TTL 与显式 stale recovery 已分离；真实离线恢复待 Windows 观察 |
| 下载/断点续传 | 200/206/416、断点大小、取消和重连已代码级修复；真实站点/Windows 待验收 |
| 队列/暂停恢复 | 主要线程与按钮语义已修；100+ 混合状态现场仍需只读/隔离验收 |
| SQLite | 有锁和写连接封装；仍有绕过入口和 schema 缺失 |
| 资源库 | 卡片搜索、后台加载和异常分类已修；递归校验、扫描快照/旧索引清理仍待完成 |
| Dashboard | 基础统计可用；依赖缺失的 library_items 和错误重建提示 |
| 迁移 | 两阶段框架合理；递归 part、library_items、验证与删除确认需修 |
| External intake | scan 可保留；execute 必须冻结后重构 |
| Backlog | 审计意识较好；备份/回滚实现需修 |
| 工具页 | 功能较多；同步阻塞、假清缓存、不可达 execute |
| 音频标签 | MP3/FLAC 基础可用；格式/MIME 支持不完整 |
| 测试/CI | 125 项 portable 门和本地 HTTP 集成已建立；历史脚本迁移与远端 CI 首跑仍待完成 |

## 建议修复顺序

1. `HOTFIX-A`：冻结 external intake execute。
2. `HOTFIX-B`：download 416、Range、target/response 清理、取消进度和重连已完成代码级修复；等待 Windows live smoke。
3. `DATA-CORE`：补齐 schema、递归验证、迁移同步 `library_items`。
4. `UI-SEMANTICS`：修复取消/强制/打开目录/重连/搜索/并发设置。
5. `TOOLS-SAFETY`：工具页后台化、实现真实清缓存、重构 backlog。
6. `TEST-GATE`：portable pytest + GitHub Actions 已完成本地定义；下一步做 Windows 只读 snapshot/UI 观察验收。

## 审查边界

本报告最初是代码级审查；后续已通过 Git Bundle 完成本地 clone、隔离依赖安装、125 项 pytest、Flet 模块导入、真实 aiohttp Range 和沙盒文件/数据库故障测试。仍缺 Windows 真实 GUI、文件锁、长路径、活跃任务现场观察和远端 GitHub Actions 首跑，因此不能替代实机验收。
