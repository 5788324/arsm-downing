# NEXT_TASK_ROADMAP.md

# arsm-downing 接手后详细任务路线图

> 起点：2026-07-18  
> 基线：`main@1f33595`  
> 当前阶段：`TAKEOVER-T6B 已完成，T7 等待维护窗口`（用户当前仍有 100+ 混合状态任务）

## 总原则

```text
不推倒重写
不直接在 main 开发
不把 UI 改动与高风险 DB/文件操作混成一个 PR
不使用真实 E:\arsm 作为默认测试夹具
不在安全收口前开发播放器
```

## TAKEOVER-T0：接手基线与冻结

### 目标

建立可信的当前状态，冻结 external intake 真实执行。

### 任务

- [x] 确认仓库权限、默认分支、近期提交、PR/Issue 状态
- [x] 建立接手分支
- [x] 新增 `CURRENT_STATE.md`
- [x] 新增 `docs/TAKEOVER_AUDIT_20260718.md`
- [x] 新增本路线图
- [x] 重写 README，使其反映 arsm-suite 当前架构
- [x] 更新 AI_WORKFLOW 为当前 ChatGPT/Codex 分工
- [x] 在 WORKLOG 追加接手记录
- [x] 给 external intake UI 增加明确 STOP 提示并禁用执行按钮
- [x] 在 `execute_normalize()` 最深层入口增加副作用前硬冻结
- [x] CLI `--execute` 固定以退出码 2 拒绝
- [x] 建立临时目录/临时 SQLite 的便携回归测试

### 验收

```text
PASS（2026-07-20）
文档与当前代码阶段一致
核心执行、元数据刷新、CLI、UI 均 fail-closed
12/12 external-intake 便携测试通过
未访问真实 E:\arsm 或 history.db
```

## TAKEOVER-T1：计划模型与纯扫描收口

### 状态

```text
PASS（2026-07-20）
```

### 已完成

- [x] 固定 `ExternalIntakePlan` schema：root、root_exists、scanned_top_dirs、unique_rj、actions、fatal_blockers、review_required、quarantine_actions、warnings、can_execute
- [x] 所有失败和空结果路径保持同一 schema
- [x] 六类目录分类：already_normalized、needs_title_layer、needs_rename_top_level、quarantine_candidate、duplicate_review、fatal
- [x] 扫描根目录和隔离目录改为配置，不再硬编码用户盘符
- [x] 增加绝对路径、文件系统根目录、路径包含、符号链接和目标逃逸检查
- [x] 增加目标路径已存在冲突检查
- [x] 重复 RJ 的所有候选均进入人工复核，不自动选择主目录
- [x] 报告保存全部 actions，不截断前 50 项
- [x] UI 只显示摘要和前 15 项，完整报告写文件
- [x] UI 扫描使用后台线程，设置页提供两个路径配置项
- [x] 删除旧的文件移动和业务 SQLite 写入实现

### 验收

```text
20/20 portable tests passed
60-action report completeness passed
missing/relative/unsafe root tests passed
duplicate RJ review tests passed
target conflict fatal tests passed
config round-trip tests passed
真实文件和数据库零副作用
```

## TAKEOVER-T2：数据库服务收口

### 状态

```text
PASS（2026-07-20）
```

### 已完成

- [x] `LibraryVault` 支持指定数据库路径、上下文关闭和 `mode=ro` 只读打开
- [x] 增加 RJ 快照接口：works、metadata title/tracks、library_items、library_index、downloads
- [x] `ExternalIntakePlan` schema v2 附加 preimage token、主路径、pending 和索引路径
- [x] Tools 页复用 AppController 现有 Vault，不创建新实例
- [x] external intake 工具移除业务 `sqlite3.connect`，只读核验通过 Vault
- [x] 新增四表统一路径事务：works、downloads、library_items、library_index
- [x] 使用 `BEGIN IMMEDIATE`、写锁和路径组件替换，不使用 SQL 字符串 `REPLACE`
- [x] 成功结果包含 preimage/postimage/token/updated_rows/transaction_id
- [x] SQLite 故障 rollback 全部表并保留 preimage
- [x] 重复副本不能覆盖正常主记录；不按 RJ 号删除记录
- [x] 同 RJ source/target index 冲突、其他 RJ 目标占用、第三路径不一致均 fail-closed
- [x] 全新数据库补齐 `library_items` 基础 schema

### 验收

```text
tools/external_intake.py 无业务 sqlite3.connect
UI 无新增 LibraryVault 实例
40/40 external-intake portable tests passed
重复 RJ 主记录保护 passed
SQLite failure rollback passed
read-only CLI database hash unchanged
真实文件与真实数据库零副作用
```

## TAKEOVER-T3：逐作品执行与自动恢复

### 状态

```text
PASS（2026-07-20，沙盒执行层）
```

### 已完成

- [x] 计划 schema v3 生成完整逐文件 source/target 映射
- [x] source manifest token 在执行前重新校验计划漂移
- [x] 每个作品独立 Journal 与状态时间线
- [x] 目标盘 staging copy；源目录同盘 rollback 暂存
- [x] staging 和 target 均校验相对路径、数量、总大小、单文件大小和关键哈希
- [x] Title 层映射同步更新 downloads 具体文件路径
- [x] DB 更新失败自动删除目标并恢复原源目录
- [x] DB 提交前进程中断自动恢复原源目录
- [x] DB 提交后进程中断保留目标并清理 rollback
- [x] 恢复失败标记 STOP，批处理不继续后续作品
- [x] Journal 路径和所有操作路径必须位于显式 sandbox
- [x] source/target 嵌套、目标占用、symlink、part、空目录和不完整映射 fail-closed
- [x] 将 manifest/映射与执行/恢复拆分为独立模块

### 验收

```text
62/62 external-intake portable tests passed
文件失败注入 rollback passed
DB failure filesystem restore passed
同名目标冲突 passed
部分批次停止 passed
DB 提交前/后崩溃恢复 passed
rollback failure -> STOP passed
Title 层与 downloads 路径一致 passed
真实 E:\arsm / history.db 零访问
```

### 仍然冻结

Tools/CLI 真实执行、quarantine 移动、needs_title_layer 自动命名和正式资源库写入仍未开放。

## TAKEOVER-T4：测试体系与 CI

### 状态

```text
PASS（2026-07-20）
```

### 已完成

- [x] 增加 `pytest.ini` 和严格 marker
- [x] 将 external intake 62 项测试纳入统一 pytest collection
- [x] 增加共享临时 SQLite / sandbox fixture
- [x] 建立统一 `python -m pytest` 命令
- [x] 区分 portable、manual、windows_integration、live_network
- [x] 增加 GitHub Actions：Linux Python 3.10 + Windows Python 3.12
- [x] 精确锁定当前兼容依赖；Flet 保持 legacy API 可用的 0.27.6
- [x] 增加 UI/core import smoke tests
- [x] 工作区出现 live `history.db/config.json/queue.json` 时测试 fail-closed
- [x] 增加活跃 SQLite 在线只读快照、integrity_check 和 SHA-256 manifest
- [x] 增加 verified snapshot 混合任务状态统计
- [x] 完成 Windows 只读验收规范

### 验收

```text
隔离 Python 3.13 环境：94/94 passed（T4 当时基线；T5A 后当前为 125）
Flet 0.27.6 ft.icons/ft.colors 与全部 UI 模块 import：PASS
pip check：PASS
WAL 并发写入 snapshot：PASS
live-state pytest guard：PASS
GitHub Actions workflow：本地语法/结构检查通过，待最终推送后真实运行
默认测试未读取 E:\arsm 或真实 history.db
```

## TAKEOVER-T5A：下载核心与隔离 UI Smoke

### 状态

```text
PASS（2026-07-20，代码级与本地网络）
```

### 已完成

- [x] HTTP 200/206/416 响应计划与严格 Content-Range/Content-Length 校验
- [x] 完整 `.part` + 416 才允许完成；不完整断点不会误报成功
- [x] 取消和失败记录真实磁盘断点大小
- [x] Range 不匹配时受控从零重试，不追加损坏响应
- [x] 有限镜像故障切换
- [x] 重连按 pause 完成后 resume；批量控制不跨线程直接操作 UI
- [x] 强制重复下载、canonical directory 和真实并发设置修复
- [x] 过期 cache 可显式用于恢复，正常请求仍使用 TTL
- [x] metadata 嵌套音轨递归显示
- [x] 本地 ASMR.one 兼容服务器和隔离 live/UI smoke 脚本
- [x] Flet legacy icon/color 常量迁移为当前锁定版本 API

### 验收

```text
125/125 portable tests passed
真实 aiohttp 200/206/416 passed
本地 1 MiB 下载、最终大小和 SHA-256 passed
正式 100+ 任务、history.db、queue.json、config.json 零访问
```

### 未完成

当前容器无法解析真实 asmr.one；Chromium 企业 URLBlocklist 和 Linux 缺少
`libmpv.so.1` 阻止视觉点击。真实站点和 Windows 桌面结论不得标记 PASS。

## TAKEOVER-T5B：Windows 在线快照、真实下载与视觉验收

### 负责人

Codex，仅执行必须依赖用户 Windows 本机的部分。

### 任务

1. 在干净 Bundle/checkout 运行当前 158 项 portable tests。
2. 保持当前 100+ 混合状态任务不变，创建在线 SQLite snapshot。
3. 输出 completed/failed/paused/queued/downloading/resuming 状态报告。
4. 在全新空 sandbox 运行 `live_download_smoke.py`，默认 RJ01575399 或其他小样本。
5. 在另一全新 sandbox 运行本地 fake server + `run_ui_smoke.py --view desktop`。
6. 检查添加、准备、排队、下载、暂停、恢复、重连、完成、失败和打开目录。
7. 截图记录布局、截断、状态文案、错误按钮、卡顿和进度异常。
8. 不在正式程序目录安装依赖或运行 smoke。

### 验收

```text
不改正式 DB、不改变正式下载队列
snapshot manifest 和 integrity_check 通过
真实 ASMR.one 小文件最终大小与 SHA-256 报告通过
Flet UI 可操作且状态机与数据库/文件结果一致
所有 smoke 产物仅位于独立 sandbox
```

## TAKEOVER-T5C：资源库 UI 与验收自动化

### 状态

```text
PASS（2026-07-20，代码级）
```

### 已完成

- [x] 资源库搜索实际传入 SQLite；支持 RJ、文件夹和路径
- [x] 非空搜索改为回车/按钮触发，避免每次按键全库扫描
- [x] 卡片分页自动钳制，搜索后不会停留在空的越界页
- [x] summary 改为 works、索引、文件、容量和警告的实时值
- [x] 移除 E 盘、用户名、固定 227、假 RJ/别名 RJ 硬编码
- [x] 异常分类基于配置的 output/library roots，支持跨 Windows/POSIX 路径
- [x] DB 查询与全库路径检查放入后台线程，回调统一返回 Flet UI queue
- [x] 异常超过 200 项时明确显示截断提示
- [x] 打开目录失败不再静默吞掉
- [x] 新增 Windows 一键验收器和 PowerShell 入口

### 验收

```text
139/139 portable tests passed
资源库搜索、分页、动态 summary、异常分类和打开目录 tests passed
Windows acceptance dry-run report passed
真实 Windows 桌面视觉仍属于 T5B Codex 验收，不在代码级 PASS 中
```

## TAKEOVER-T6：沙盒执行验收

### 状态

```text
PASS（2026-07-20，复制资源库代码级验收）
```

### 已完成

- [x] 构造正常改名、Title 层待复核、重复 RJ、空目录、`.part` 和已规范样本
- [x] 在临时资源库和临时 SQLite 上执行完整 staging / target / DB 流程
- [x] 第二次扫描回到 `already_normalized`，验证幂等
- [x] 注入数据库失败，验证 source 恢复且 target 不存在
- [x] 注入 DB 提交后清理失败，验证 Journal STOP 和后续恢复
- [x] 验证重复 RJ 的数据库主记录不被覆盖
- [x] 验收脚本只允许新目录或带专用 marker 的既有 sandbox，不删除普通现有目录
- [x] 输出完整 JSON evidence

### 验收

```text
11/11 acceptance checks PASS
第二次 dry-run 无新增整理动作
数据库路径与最终目录一致
DB 失败项自动回滚
提交后清理失败可按 Journal 恢复
正常主记录不受重复目录影响
```

详细说明：`docs/TAKEOVER_T6_SANDBOX_ACCEPTANCE.md`。

## TAKEOVER-T6B：Tools 与 backlog 安全收口

### 状态

```text
PASS（2026-07-20，代码级）
```

### 已完成

- [x] 队列清理改为只读预览；不删除 SQLite 行、不改写 `queue.json`
- [x] 缓存清理只删除过期且未被活动/暂停/失败/恢复任务引用的记录
- [x] 缓存 preview token 变化时 fail-closed
- [x] VACUUM 使用独立连接并在任何活动/可恢复行存在时拒绝
- [x] 系统诊断只读，不再为了权限测试创建输出目录
- [x] 网络诊断不再把代理地址当作目标网页，结果回到 UI queue
- [x] backlog 预览移除特定 RJ 硬编码并统计混合状态全部行
- [x] backlog 执行要求运行时完全空闲，加锁后再次校验 preimage
- [x] 默认 `continue` 保留断点；`.part` 存在时拒绝 `retry-from-zero`
- [x] SQLite online backup、preimage、rollback SQL 和 post-verify 全部使用临时测试验证
- [x] 两个旧 backlog 诊断脚本改为 `TemporaryDirectory + 临时 SQLite`

详细说明：`docs/TOOLS_MAINTENANCE_SAFETY.md`。


## TAKEOVER-T8B：资源库快照重建与索引一致性

### 状态

```text
PASS（2026-07-20，代码级）
```

### 已完成

- [x] 扫描阶段只生成完整快照，不边扫描边写数据库
- [x] `library_items` / `library_index` 同一事务整体替换
- [x] 自动删除不存在目录对应的陈旧索引
- [x] 重复 RJ 保留全部 index，卡片主路径优先沿用现有数据库路径
- [x] 新外部作品补入 works；活动/可恢复下载的 works 路径保持不变
- [x] 扫描中断、目录消失和数据库失败时保留旧索引
- [x] metadata folder/children 任意层级递归验证
- [x] Tools 页后台执行并展示新增、更新、清理和缺失统计
- [x] 独立沙盒验收 10/10 PASS

详细说明：`docs/TAKEOVER_T8B_LIBRARY_REBUILD.md`。

## TAKEOVER-T7：真实小批量验收

### 前置条件

T1~T6 全部通过，并且目标 RJ 不存在 queued/downloading/resuming/paused/failed 下载行。活跃下载器未退出时不得进行真实小批量执行。

### 范围

最多选择 1~3 个无争议作品，只执行目录规范化；重复 RJ、缺文件、part 文件继续人工复核，不在首批执行。

### 验收

- 执行前备份存在
- plan 与实际一致
- DB integrity ok
- 资源库 UI 可打开
- 下载页无异常任务污染
- 回滚信息完整

## TAKEOVER-T8：功能恢复与后续阶段

external intake 通过后再按以下顺序推进：

1. 下载器真实新任务恢复验证
2. metadata_cache 清理/重建决策
3. ToolsView 简化与异步化
4. README/安装运行体验完善
5. 播放器技术验证
6. P7 播放器 MVP


## TAKEOVER-T9：发布候选收口

### 状态

```text
PASS（2026-07-20，代码级）
```

### 已完成

- [x] 版本统一为 `0.9.0-rc.1`，窗口标题和 Windows 版本资源一致
- [x] 源码/便携版运行目录稳定，不依赖快捷方式工作目录
- [x] 配置使用临时文件、fsync 和原子替换
- [x] 关闭流程等待 active/workers，关闭 HTTP、SQLite 和事件循环
- [x] 音频标签扩展到 MP3/FLAC/OGG/Opus/M4A/WAV/AIFF/WMA
- [x] 封面 MIME 按文件签名识别；OGG/Opus/MP4 cover 支持
- [x] 重建 PyInstaller one-folder spec，移除本机临时路径
- [x] 增加 Windows 构建脚本、release workflow、release_check 和交接文档
- [x] Linux PyInstaller Analysis/PYZ/EXE/COLLECT 通过
- [x] portable tests 204/204 通过

### 待外部证据

- [ ] GitHub Linux/Windows CI
- [ ] GitHub Windows release artifact
- [ ] Codex Windows EXE 启动/关闭和 Flet Desktop 截图
- [ ] 真实 ASMR.one 小样本下载

## 当前下一项

```text
TAKEOVER-T9：已完成——0.9.0-rc.1 发布候选、音频标签、运行目录、关闭流程和构建链
TAKEOVER-T5B：立即下一项——GitHub CI + Windows/Codex 真实下载、EXE 和 UI 证据
TAKEOVER-T7：继续暂停——等待 100+ 混合任务清空后的维护窗口
后续版本：播放器 MVP 和历史脚本归档
```
