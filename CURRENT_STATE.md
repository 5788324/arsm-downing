# ARSM Suite 当前状态

> 更新时间：2026-07-22  
> 当前版本：`0.9.0-rc.1`  
> 发布候选分支：`chatgpt/takeover-20260718`  
> 合并目标：`main`

## 1. 项目定位

ARSM Suite 是一个仅供个人本地使用的 Windows ASMR/RJ 媒体库桌面工具，采用 Python、Flet、SQLite、asyncio 和 aiohttp，继续保持为单体桌面应用。

主要能力：

- ASMR.one 作品下载、断点续传、暂停、恢复和失败重试；
- SQLite 下载状态和资源库数据管理；
- 本地资源库扫描、搜索、异常识别和快照重建；
- External Intake 只读计划、文件事务、Journal、回滚和恢复；
- 目录迁移 dry-run、manifest 校验、四表同步和失败回滚；
- Tools 页的缓存、队列、VACUUM、backlog 和诊断工具；
- Windows PyInstaller 便携版构建。

播放器仍属于后续版本，不进入 `0.9.0-rc.1`。

## 2. 必须保持的架构约束

```text
history.db / SQLite = 唯一业务真源
LibraryVault = 唯一正式数据库访问入口
UI 不直接 sqlite3.connect()
扫描 JSON / manifest 不作为 UI 主数据源
文件移动、隔离、删除必须先 dry-run，并保留可验证回滚信息
```

## 3. 已完成阶段

```text
TAKEOVER-T0~T4   External Intake 冻结、计划模型、数据库事务、文件事务、CI
TAKEOVER-T5A     下载核心、断点、HTTP 200/206/416 和隔离 UI smoke
TAKEOVER-T5C     资源库 UI、搜索、分页、异常诊断和后台加载
TAKEOVER-T6/T6B 复制资源库沙盒验收、Tools 和 backlog 收口
TAKEOVER-T8A     迁移 manifest、递归 part/symlink、四表同步和回滚
TAKEOVER-T8B     资源库快照重建、原子索引替换和陈旧索引清理
TAKEOVER-T9      版本、运行目录、关闭流程、音频标签和发布构建链
```

核心代码、资源库、迁移、External Intake 沙盒、Tools、测试体系和构建链已完成发布候选级收口。

## 4. GitHub 与 CI 状态

PR：`#1 release: prepare ARSM Suite 0.9.0-rc.1`

发布候选验收提交：

```text
237ceab9d083a8f53b8169a0333bb63137d9566b
```

最新正式 portable CI：

```text
GitHub Actions run：29848754898
Ubuntu / Python 3.10：PASS
Windows / Python 3.12：PASS
compileall：PASS
Flet import smoke：PASS
portable pytest：205/205 PASS
```

Windows 临时目录 8.3/别名路径问题已修复：生产事务保留数据库原始路径拼写，测试断言不再通过 `Path.resolve()` 改写 Windows 路径。

## 5. Windows 发布候选构建

Windows release workflow：

```text
Run：29834355321
结论：PASS
```

已通过：

- release checks；
- PyInstaller one-folder 构建；
- `ARSM-Suite.exe` 存在性检查；
- ZIP 和 SHA-256 生成；
- Artifact 上传。

产物：

```text
ARSM-Suite-0.9.0-rc.1-windows-x64.zip
SHA-256：b60125d5fddebd056d292a8dccb485d512d52eb65865db9534e1a874de20f2cb
```

## 6. Windows 自动验收结论

在 GitHub `windows-latest` 的真实 Windows Server 2025 Runner 中完成：

- 从 Artifact 解压便携包：PASS；
- SHA-256 独立复核：PASS；
- 在含中文和空格的隔离路径启动 `ARSM-Suite.exe`：PASS；
- EXE 启动后持续存活 15 秒：PASS；
- `config.json` 和 `history.db` 仅生成于隔离 App 目录：PASS；
- 正式仓库目录无运行状态文件泄漏：PASS。

Flet Web/Playwright 在 Hosted Runner 的无交互浏览器中停留于 Flet 加载页。服务端正常监听并返回 HTTP 200，EXE 没有崩溃；这不能替代用户桌面上的 Flet Desktop 肉眼验收，也不判定为产品失败。

最终自动验收结论：

```text
PASS_WITH_NOTES
```

## 7. 正式环境状态

开发、CI 和沙盒验收均未：

- 连接或修改用户正式 `history.db`；
- 读取、移动或删除真实 `E:\arsm`；
- 修改正式 `config.json` 或 `queue.json`；
- 改动用户现有 100+ completed/failed/paused/queued/downloading 混合任务；
- 覆盖当前仍在运行的正式程序目录。

历史 2026-06-28 的 `works=184` 等记录仅是旧快照，不代表当前现场状态。

## 8. 当前继续冻结的操作

```text
python tools/external_intake.py --execute --confirm-bulk
External Intake 正式执行入口
正式资源库批量迁移和隔离
正式数据库 VACUUM
正式 backlog execute
T7 真实 1~3 个作品目录整理
```

这些操作要等现有混合下载任务自然清空或进入明确维护窗口后再决定是否开放。

## 9. 尚未覆盖但不阻塞 RC 合并

1. 用户桌面上的 Flet Desktop 肉眼布局、实际鼠标操作和截图；
2. 真实 ASMR.one 网络小样本下载；
3. Windows Defender、长路径和第三方文件占用的现场观察；
4. 正式数据库在线快照和真实资源库小批量验收。

这些事项在稳定版之前或后续维护窗口完成，不阻止 `0.9.0-rc.1` 作为发布候选合并。

## 10. 当前下一步

```text
1. PR #1 最终 CI 通过后转为 Ready
2. Squash Merge 到 main
3. 在 main 合并提交创建 v0.9.0-rc.1 标签
4. 标签触发 Windows release workflow
5. 下载并复核从 main 构建的 ZIP 与 SHA-256
6. 后续版本处理真实桌面验收、真实网络样本和播放器
7. T7 继续等待维护窗口
```

## 11. 当前结论

```text
ARSM Suite 已进入 0.9.0-rc.1 合并阶段。
代码级发布候选、Linux/Windows CI、Windows Artifact 和便携 EXE 启动均已通过。
当前结论为 PASS_WITH_NOTES，可以合并到 main。
```
