# ARSM Suite 当前状态

> 更新时间：2026-07-23  
> 当前版本：`0.9.0-rc.1`  
> 当前分支基线：`main@9f292e7947804f2e4d53290039501f79c6d1805d`  
> 当前阶段：Post-RC 稳定化与大队列优化规划

## 1. 项目定位

ARSM Suite 是一个仅供个人本地使用的 Windows ASMR/RJ 桌面工具，继续保持为单体 Flet 应用。

当前能力包括：

- ASMR.one 下载、断点续传、暂停、恢复和失败重试；
- SQLite 下载状态与资源库数据管理；
- 资源库搜索、分页、异常识别和快照式索引重建；
- External Intake 计划、文件事务、Journal、回滚和恢复；
- 目录迁移 dry-run、manifest、四表同步和失败回滚；
- 队列、缓存、VACUUM、backlog 和诊断工具；
- Windows PyInstaller one-folder 构建。

播放器仍属于后续产品阶段，不进入当前稳定化任务。

## 2. 必须保持的架构约束

```text
history.db / SQLite = 唯一业务真源
LibraryVault = 唯一正式数据库访问入口
UI 不直接 sqlite3.connect()
queue.json 不作为历史下载状态真源
扫描 JSON / manifest 不作为 UI 主数据源
文件移动、隔离和删除必须先 dry-run，并保留可验证回滚信息
```

## 3. 已完成阶段

```text
TAKEOVER-T0~T4   External Intake 冻结、计划模型、事务层和统一 CI
TAKEOVER-T5A     下载核心、HTTP 200/206/416、断点与隔离网络 smoke
TAKEOVER-T5C     资源库 UI、搜索、分页、异常诊断和后台加载
TAKEOVER-T6/T6B 复制资源库沙盒验收、Tools 与 backlog 安全收口
TAKEOVER-T8A     迁移 manifest、递归 part/symlink、四表同步和回滚
TAKEOVER-T8B     资源库快照重建、原子索引替换和陈旧索引清理
TAKEOVER-T9      版本、运行目录、关闭流程、音频标签和发布构建链
```

上述代码已通过 PR #1 合并到 `main`。

## 4. GitHub 与发布状态

PR #1：`release: prepare ARSM Suite 0.9.0-rc.1`

```text
状态：MERGED
合并时间：2026-07-21
main merge commit：9f292e7947804f2e4d53290039501f79c6d1805d
```

正式 portable CI：

```text
Ubuntu / Python 3.10：PASS
Windows / Python 3.12：PASS
compileall：PASS
Flet import smoke：PASS
portable pytest：205/205 PASS
```

Windows release workflow：

```text
Run：29834355321
结论：PASS
```

发布产物：

```text
ARSM-Suite-0.9.0-rc.1-windows-x64.zip
SHA-256：b60125d5fddebd056d292a8dccb485d512d52eb65865db9534e1a874de20f2cb
```

## 5. Windows 自动验收

GitHub `windows-latest` 隔离环境已验证：

- Artifact 解压：PASS；
- SHA-256 复核：PASS；
- 含中文和空格的路径启动：PASS；
- EXE 持续存活：PASS；
- `config.json` 和 `history.db` 仅生成在隔离 App 目录：PASS；
- 仓库和正式目录无状态文件泄漏：PASS。

自动结论：

```text
PASS_WITH_NOTES
```

仍缺少的现场证据：

1. 用户桌面上的 Flet Desktop 肉眼布局和实际鼠标操作；
2. 真实 ASMR.one 网络小样本；
3. Windows Defender、长路径和第三方文件占用观察。

DeepSeek 提交的旧验收包只证明程序曾打开首页，不能证明三次正常关闭、五页视觉、真实下载或文件系统边界，因此不作为最终桌面证据。

## 6. 正式环境状态

开发、CI、构建和自动验收均未：

- 连接或修改用户正式 `history.db`；
- 读取、移动或删除真实 `E:\arsm`；
- 修改正式 `config.json` 或 `queue.json`；
- 改动现有 100+ completed/failed/paused/queued/downloading 混合任务；
- 覆盖当前运行中的正式程序目录。

历史数据库统计只代表旧快照，不能当作当前现场实时状态。

## 7. 当前冻结操作

```text
python tools/external_intake.py --execute --confirm-bulk
External Intake 正式 execute
正式资源库批量迁移、移动、隔离或删除
正式 history.db VACUUM
正式 backlog execute
T7 真实 1~3 个作品目录整理
```

解除冻结的前提：

- 当前混合任务自然清空或进入明确维护窗口；
- 生成在线只读 SQLite snapshot 与 manifest；
- 先在复制资源库和临时数据库中验收；
- 正式环境只开放小批量、可回滚执行。

## 8. ARSM Library v2 分支结论

`ARSM-Library-v2-source-20260722` 已放弃，不再作为独立分支继续开发，也不替代当前主线。

原因：

- 不继承旧数据库、旧队列和旧 `.part`；
- 正式库只读边界与代码行为冲突；
- 416、Content-Range 和最终大小校验弱于当前下载核心；
- 暂存目录重复检测存在缺陷；
- 真实 API 认证和真实下载未完成；
- 没有当前主线的构建、迁移和正式任务兼容能力。

允许吸收的仅是设计思想：

- UI → Service → LibraryVault 的只读门面；
- 批量队列快照；
- 元数据与音频下载并发池分离；
- 批量添加预览；
- 显式状态迁移；
- 页面激活生命周期；
- 资源库详情侧栏；
- 后续可选托盘模式。

明确不吸收：

```text
新的 library.db
新的 download_tasks/download_files 表
v2 下载引擎
v2 设置保存实现
正式库直入开关
整套 v2 Flet 页面代码
```

## 9. 当前下一步

当前最高优先级为 `TAKEOVER-T10`：

```text
Queue Service 与 100+ 任务性能优化
```

范围：

1. 新增下载只读模型和轻量 Service 门面；
2. 增加批量队列快照，消除 UI N+1 查询；
3. 将下载状态推导移出 Flet View；
4. 增加批量 RJ 预览、查重和统一确认；
5. 分离 metadata queue 与 download queue；
6. 增加页面 active/inactive 生命周期；
7. 增加状态迁移规则与测试。

边界：

```text
不改现有数据库表结构
不替换下载核心
不改现有 .part 语义
不访问正式数据库或真实 E:\arsm
不加入托盘
不开发播放器
```

详细任务见 `NEXT_TASK_ROADMAP.md` 与 `docs/POST_RC_OPTIMIZATION_BACKLOG.md`。

## 10. 当前结论

```text
ARSM Suite 0.9.0-rc.1 已合并到 main。
代码、Linux/Windows CI、Windows Artifact 和隔离 EXE 启动均已通过。
当前不再处于“等待 RC 合并”阶段，而是 Post-RC 稳定化阶段。
下一轮先做低风险的大队列性能和 UI 状态分层，不触碰生产数据与下载核心。
```
