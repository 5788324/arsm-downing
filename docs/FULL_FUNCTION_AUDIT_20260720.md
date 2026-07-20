# arsm-downing 全功能代码审查

> 修复状态：TAKEOVER-T0/T1 已完成 external intake 硬冻结、固定计划模型、路径配置、冲突分类、完整报告和后台 UI 扫描；其余下载、数据层、UI、迁移和工具问题仍按本文优先级推进。

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
- 测试数量很多，但没有统一、可移植、可信的 pytest/CI 门禁。

## P0：可能造成数据损坏、错误完成或不可恢复状态

### P0-01 External intake 旧执行入口仍可写真实文件与数据库

- UI 仍保留“执行整理”。
- 旧实现直接移动/隔离目录并直接写 SQLite。
- 重复 RJ 的隔离路径可能删除正常主记录。
- 文件系统与数据库更新没有可靠原子恢复。

处理：保持 Issue #2，先代码级冻结 execute，仅保留 scan/dry-run。

### P0-02 下载断点续传的 HTTP 416 处理不可信

- HTTP 416 当前可直接标记 `completed`，未校验最终文件或 `.part` 文件是否真的等于目标大小。
- 响应处理 `finally` 可能在 `target` 尚未赋值时引用它。
- 取消时写回的 `downloaded_bytes` 可能是旧值，而不是当前 `.part` 实际大小。

处理：统一完成判定为“本地文件存在 + 大小精确匹配”；所有分支先初始化 target；取消时从磁盘重新取值。

### P0-03 资源库完整性校验不递归

`verify_library_item()` 遇到 metadata folder 仅跳过 folder 本身，没有递归验证 children，可能将嵌套音轨缺失的作品标记为 `verified`。

处理：复用统一的递归 track flatten，并按相对路径或可解释匹配规则验证。

### P0-04 迁移后数据库视图不完整

迁移只更新：

- `works.local_path`
- `downloads.local_path`
- `library_index`

未更新/重建 `library_items`，资源库卡片仍可能指向旧路径；迁移验证也没有检查 `library_items`。

处理：在同一数据库事务中更新或重建目标作品的 `library_items`，并加入 post-verify。

### P0-05 迁移可能漏检嵌套 `.part`

`_has_part_files()` 只扫描源目录顶层。子目录中的 `.part` 不会阻止迁移。

处理：改为递归扫描；测试顶层与多层嵌套。

### P0-06 新数据库缺少完整 schema

`LibraryVault._init_schema()` 创建 `works`、`metadata_cache`、`downloads`、`library_index`，但资源库 UI 直接查询 `library_items`。全新安装或新数据库可能出现资源库/统计为空或查询错误。

处理：建立完整 schema 版本与迁移入口，至少覆盖 `library_items` 及其索引。

## P1：主要功能错误或高概率 UI/状态异常

### P1-01 Flet UI 跨线程更新混用

项目已经建立 UI 消息队列，但部分后台协程仍直接调用控件更新、SnackBar、日志 ListView 和队列刷新。可能产生偶发 UI 冻结、更新丢失或关闭异常。

处理：所有后台结果统一进入主线程消息队列。

### P1-02 设置页并发滑块无效

设置页保存 `max_concurrent`，实际下载器使用 `work_concurrency` 和 `file_concurrency`。用户修改“最大并发下载数”不会改变真实下载行为。

处理：拆成“同时下载作品数”和“每个作品同时下载文件数”，保存真实字段，并明确重启/动态生效策略。

### P1-03 下载页按钮语义与行为不一致

- “仍然下载/强制下载”未传 `allow_duplicate=True`，仍会被核心重复检查拦截。
- “取消下载”实际调用 pause，只隐藏卡片，DB 中暂停记录仍保留。
- “打开目录”按当前模板重新拼路径，不读取数据库真实 `local_path`，迁移后可能打开错误目录。
- “重连”同时调度 pause/resume，存在竞态。
- 暂停/失败任务读取的 queue.json tracks 随后被丢弃。
- 批量恢复混合列表中仍会遍历 failed-only 项。

处理：明确 pause/cancel/remove 三种动作，所有按钮调用可验证的核心服务接口。

### P1-04 资源库搜索失效

搜索框会触发刷新，但卡片查询和计数未传入 search 参数；异常视图也没有应用搜索词。

处理：统一 query state，卡片与异常模式都使用相同搜索条件。

### P1-05 资源库和工具页硬编码本机状态

- `E:\arsm`
- 旧用户路径
- 特定假 RJ/别名 RJ
- `磁盘扫描: ~227`
- backlog 排除特定 RJ

处理：路径来自配置；历史一次性清理数据移入迁移脚本/审计文件，不进入通用 UI 逻辑。

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

- requirements 未锁版本。
- 没有统一 pytest 配置和 GitHub Actions。
- 大量 `scripts/test_*.py` 是分散脚本，包含静态字符串检查与本机路径依赖，不能等同于完整回归测试。

## 功能域结论

| 功能域 | 结论 |
|---|---|
| 启动/关闭 | 可用基础存在；线程关闭与 UI 回调需收口 |
| 配置/设置 | 基础可用；并发设置失效、验证不足 |
| 网络/代理 | 三通道代理基础可用；镜像切换和诊断需修 |
| 元数据 | 缓存与在线获取可用；TTL 与恢复语义冲突 |
| 下载/断点续传 | 架构较完整；416、取消、重连、完成判定需优先修 |
| 队列/暂停恢复 | 基础可用；UI 与 DB 动作语义不统一 |
| SQLite | 有锁和写连接封装；仍有绕过入口和 schema 缺失 |
| 资源库 | 卡片/异常页已有；搜索、校验、扫描快照存在问题 |
| Dashboard | 基础统计可用；依赖缺失的 library_items 和错误重建提示 |
| 迁移 | 两阶段框架合理；递归 part、library_items、验证与删除确认需修 |
| External intake | scan 可保留；execute 必须冻结后重构 |
| Backlog | 审计意识较好；备份/回滚实现需修 |
| 工具页 | 功能较多；同步阻塞、假清缓存、不可达 execute |
| 音频标签 | MP3/FLAC 基础可用；格式/MIME 支持不完整 |
| 测试/CI | 测试脚本数量多；尚未形成可信门禁 |

## 建议修复顺序

1. `HOTFIX-A`：冻结 external intake execute。
2. `HOTFIX-B`：修复 download 416、target 初始化、取消进度写回。
3. `DATA-CORE`：补齐 schema、递归验证、迁移同步 `library_items`。
4. `UI-SEMANTICS`：修复取消/强制/打开目录/重连/搜索/并发设置。
5. `TOOLS-SAFETY`：工具页后台化、实现真实清缓存、重构 backlog。
6. `TEST-GATE`：portable pytest + GitHub Actions，再做 Windows 小批量验收。

## 审查边界

本报告是代码级全功能审查。由于当前运行环境无法解析 `github.com`，尚未完成本地 clone、依赖安装、pytest 和 Flet GUI 实机运行。因此报告不能替代后续自动化测试与 Windows 实机验收；所有问题会在修复 PR 中逐项加入回归测试。
