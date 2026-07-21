# arsm-downing / arsm-suite

面向个人本地使用的 Windows ASMR/RJ 媒体库桌面工具。

项目继续保持为一个单体 Flet 应用，在同一程序内整合：

- ASMR.one 下载器
- 下载队列与断点续传
- SQLite 状态与资源库数据层
- 本地资源库管理
- 目录迁移与外部资源接入工具
- 后续本地音频播放器

> 当前接手状态与风险说明请先阅读 [`CURRENT_STATE.md`](CURRENT_STATE.md)。  
> 当前详细任务路线图见 [`NEXT_TASK_ROADMAP.md`](NEXT_TASK_ROADMAP.md)。

## 当前技术栈

```text
Python 3.10+
Flet
SQLite
asyncio
aiohttp / aiofiles
mutagen
```

主入口：

```bash
python main.py
```

## 核心架构约束

```text
history.db / SQLite = 业务唯一真源
LibraryVault = 正式数据库访问入口
queue.json 不作为历史下载进度真源
资源库 UI 通过 LibraryVault / SQLite 获取数据
扫描 JSON 和 manifest 只作为报告或缓存，不作为 UI 主数据源
```

## 当前功能

### 下载器

- 单个 RJ 添加
- 文本批量导入 RJ
- 元数据缓存
- 下载队列
- 暂停、恢复、失败重试
- HTTP Range 断点续传与 200/206/416 严格校验
- 下载速度统计
- 过期 metadata cache 的受控离线恢复
- 镜像故障切换与隔离下载 smoke test
- metadata / cover / download 三通道代理
- 音频标签写入

### 资源库

- SQLite `works` / `library_items` / `library_index` 数据模型
- 作品卡片与封面
- RJ/标题/路径搜索（回车触发，避免每次按键全库扫描）
- 后台加载、条件过滤与分页
- 配置根目录驱动的资源异常视图
- 打开本地目录并显示明确错误
- Dashboard 数据统计

### 工具

- 下载状态诊断
- 资源库扫描与索引重建
- 迁移 manifest dry-run、沙盒执行与四表 post-verify
- backlog 只读预览与受控重新启用
- 活跃任务感知的数据库维护、缓存安全清理和队列清理预览
- 外部资源接入扫描、计划生成和复制资源库沙盒验收

## 当前重要状态

当前发布候选版本：`0.9.0-rc.1`。

已完成代码级收口：

- HTTP 200/206/416、Range、`.part`、暂停/恢复和镜像切换。
- 资源库后台搜索、快照重建、陈旧索引清理和递归音轨验证。
- 迁移与 External Intake 的 staging、manifest、四表事务、Journal 和沙盒回滚。
- Tools 缓存、VACUUM、队列清理预览和 backlog 受控恢复。
- MP3/FLAC/OGG/Opus/M4A/WAV/AIFF/WMA 标签与真实封面 MIME。
- 稳定运行目录、原子配置保存、幂等关闭和 PyInstaller one-folder 构建。

当前仍保持冻结：

- External Intake 真实 execute。
- 正式资源库批量迁移和隔离。
- 正式 backlog 批量恢复和 VACUUM。
- 当前 100+ 混合下载任务运行期间的维护操作。

Windows 最终验收仍需 Codex 完成：真实 ASMR.one 小样本、Flet Desktop 视觉、Windows 文件锁/长路径和 release artifact。

详细说明：

```text
CURRENT_STATE.md
HANDOFF.md
docs/TAKEOVER_T9_RELEASE_CANDIDATE.md
docs/BUILD_AND_RELEASE.md
```

## 安装

### 1. 获取代码

```bash
git clone https://github.com/5788324/arsm-downing.git
cd arsm-downing
```

### 2. 创建虚拟环境（推荐）

Windows PowerShell：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 创建本地配置

复制示例配置：

```powershell
Copy-Item config.example.json config.json
```

然后按本机情况配置：

- `output_dir`：主下载/资源库目录
- `library_paths`：额外只读扫描根目录
- `external_intake_root`：外部资源只读计划的扫描目录
- `external_quarantine_root`：未来隔离目标目录，必须位于扫描目录之外
- `metadata_proxy`：元数据请求代理
- `cover_proxy`：封面请求代理
- `download_proxy`：音频下载代理，留空时通常直连

`config.json` 属于本机配置，不应提交到 Git。

只读计划也可以从命令行生成：

```powershell
python tools/external_intake.py `
  --root "E:\arsm" `
  --quarantine-root "E:\arsm_quarantine_external"
```

该命令只扫描并生成 `.local_backups/external_intake_*` 报告；不会移动文件或修改数据库。

### 5. 启动

```bash
python main.py
```

### 6. Windows 便携版构建

```powershell
.\scripts\build_windows.ps1
```

详见 [`docs/BUILD_AND_RELEASE.md`](docs/BUILD_AND_RELEASE.md)。

## 项目结构

```text
main.py                     Flet 应用入口
core/
  config.py                 配置与原子保存
  paths.py                  源码/便携版运行目录
  version.py                应用版本
  audio.py                  多格式音频标签与封面
  database.py               LibraryVault / SQLite 数据层
  database_snapshot.py      活跃 SQLite 在线只读快照
  database_inspection.py    快照完整性与任务状态报告
  intake_db.py               External intake 快照、路径事务与重复 RJ 保护
  network.py                网络与代理
  orchestrator.py           下载调度与状态流
  migration.py              迁移计划、执行、回滚与 post-verify
  migration_manifest.py     迁移文件清单、相对路径和哈希验证
  status.py                 状态归一化
ui/
  app.py                    应用控制器与导航
  views/                    Dashboard、下载、资源库、工具、设置
tools/                      backlog、批量核验、external intake 等工具
scripts/                    手动诊断、快照工具与兼容脚本
docs/                       规范、验收、构建与接手审计
HANDOFF.md                  Windows/Codex 最终交接
ARSMSuite.spec              PyInstaller one-folder 构建
CURRENT_STATE.md             当前事实基线
NEXT_TASK_ROADMAP.md         当前详细执行路线图
PROJECT_ROADMAP.md           历史/总体路线图
WORKLOG.md                   历史工作日志
AI_WORKFLOW.md               AI 协作与 Git 工作流规范
```

## 测试与活跃下载保护

项目已建立统一测试门：

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

默认测试只收集 `tests/`，排除 `manual`、`windows_integration` 和 `live_network`。大量历史 `scripts/test_*.py` 暂时作为兼容/诊断脚本保留，不会被误当成默认自动测试。

如果当前程序仍在下载，不要升级其环境，也不要在生产工作目录运行测试。对活跃数据库使用在线只读快照：

```powershell
python scripts/create_db_snapshot.py `
  --source "<ACTIVE_APP_DIR>\history.db" `
  --output "<TEST_DIR>\history.snapshot.db"

python scripts/inspect_db_snapshot.py `
  --snapshot "<TEST_DIR>\history.snapshot.db"
```

该流程不手工复制 WAL/SHM，不暂停或修改队列，并通过 manifest SHA-256 验证快照。详细规则见 [`docs/TESTING_AND_CI.md`](docs/TESTING_AND_CI.md) 和 [`docs/WINDOWS_READ_ONLY_ACCEPTANCE.md`](docs/WINDOWS_READ_ONLY_ACCEPTANCE.md)。

## 开发与协作

接手后默认流程：

```text
chatgpt/* 分支
-> Draft Pull Request
-> 代码审查与可执行测试
-> Windows/Codex 实机验收（仅必要部分）
-> 合并 main
```

项目仅供个人使用，不以商业化、公开分发或企业级流程为目标；但涉及真实文件移动、数据库更新和批量删除/隔离的功能，必须保留 dry-run、审计记录和可恢复能力。

## 文档入口

- [`CURRENT_STATE.md`](CURRENT_STATE.md)：当前项目事实、禁止事项与阶段
- [`NEXT_TASK_ROADMAP.md`](NEXT_TASK_ROADMAP.md)：接手后的详细执行任务
- [`docs/TAKEOVER_AUDIT_20260718.md`](docs/TAKEOVER_AUDIT_20260718.md)：代码与流程风险审计
- [`docs/ARSM_LIBRARY_SPEC.md`](docs/ARSM_LIBRARY_SPEC.md)：资源库目录规范
- [`docs/EXTERNAL_INTAKE_DB_TRANSACTION_SPEC.md`](docs/EXTERNAL_INTAKE_DB_TRANSACTION_SPEC.md)：外部接入数据库事务与恢复数据模型
- [`docs/TAKEOVER_T6_SANDBOX_ACCEPTANCE.md`](docs/TAKEOVER_T6_SANDBOX_ACCEPTANCE.md)：复制资源库沙盒执行和故障恢复证据
- [`docs/TOOLS_MAINTENANCE_SAFETY.md`](docs/TOOLS_MAINTENANCE_SAFETY.md)：队列、缓存、VACUUM 和 backlog 的维护边界
- [`docs/TAKEOVER_T8A_MIGRATION_SAFETY.md`](docs/TAKEOVER_T8A_MIGRATION_SAFETY.md)：迁移 manifest、四表事务、删除确认和沙盒证据
- [`docs/TESTING_AND_CI.md`](docs/TESTING_AND_CI.md)：便携测试门、依赖和活跃数据保护
- [`docs/WINDOWS_READ_ONLY_ACCEPTANCE.md`](docs/WINDOWS_READ_ONLY_ACCEPTANCE.md)：运行中下载器的只读验收步骤
- [`docs/CURRENT_FUNCTIONS_REVIEW_20260628.md`](docs/CURRENT_FUNCTIONS_REVIEW_20260628.md)：2026-06-28 功能与本机历史快照
- [`WORKLOG.md`](WORKLOG.md)：历史开发记录

## License

Based on `takoyune/asmr.one-downloader` and licensed under the MIT License. See [`LICENSE`](LICENSE).
