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
- HTTP Range 断点续传
- 下载速度统计
- metadata / cover / download 三通道代理
- 音频标签写入

### 资源库

- SQLite `works` / `library_items` / `library_index` 数据模型
- 作品卡片与封面
- RJ/标题搜索
- 条件过滤与分页
- 资源异常视图
- 打开本地目录
- Dashboard 数据统计

### 工具

- 下载状态诊断
- 资源库扫描与索引重建
- 迁移 dry-run / execute / verify
- backlog 预览与重新启用
- 数据库完整性检查与维护
- 外部资源接入扫描与计划生成

## 当前重要状态

仓库最新阶段正在收口外部资源接入功能。该功能涉及批量目录整理、隔离和数据库路径更新，目前真实执行入口保持 **代码级硬冻结**：

- 旧的文件移动、隔离和业务 SQLite 写入实现已从 `tools/external_intake.py` 删除。
- `execute_normalize()`、元数据刷新和 CLI `--execute` 均在副作用前固定 STOP。
- Tools 页以明确的 `READ-ONLY` 卡片展示，扫描在后台线程执行，真实执行按钮禁用。
- 只读计划使用固定 `ExternalIntakePlan` schema，完整报告不会截断 actions。
- 重复 RJ 的全部候选进入人工复核；不再自动选择主目录或删除主记录。
- 扫描根目录、隔离目录由配置提供，不再硬编码 `E:\arsm`。

旧命令现在只会得到明确 STOP，不会移动文件或修改数据库：

```bash
python tools/external_intake.py --execute --confirm-bulk
```

详细原因见：

```text
docs/TAKEOVER_AUDIT_20260718.md
```

只读扫描、临时目录测试和普通下载/资源库代码审查不受影响。

当前 external-intake 便携回归测试：

```bash
python -m unittest discover -s tests -p "test_external_intake_*.py" -v
```

当前结果：`20/20 passed`。默认测试仅使用临时目录和临时 SQLite。

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

## 项目结构

```text
main.py                     Flet 应用入口
core/
  config.py                 配置
  database.py               LibraryVault / SQLite 数据层
  network.py                网络与代理
  orchestrator.py           下载调度与状态流
  migration.py              资源迁移
  status.py                 状态归一化
ui/
  app.py                    应用控制器与导航
  views/                    Dashboard、下载、资源库、工具、设置
tools/                      backlog、批量核验、external intake 等工具
scripts/                    回归测试与诊断脚本
docs/                       规范、功能审查与接手审计
CURRENT_STATE.md             当前事实基线
NEXT_TASK_ROADMAP.md         当前详细执行路线图
PROJECT_ROADMAP.md           历史/总体路线图
WORKLOG.md                   历史工作日志
AI_WORKFLOW.md               AI 协作规范（待按当前分工更新）
```

## 测试现状

仓库已有大量 `scripts/test_*.py` 回归脚本，但尚未完成统一 pytest 入口与 GitHub Actions CI。

部分脚本依赖用户 Windows 本机路径或真实数据库，不应在未知环境中盲目全量运行。接手阶段将先把默认测试改造成：

```text
临时目录
临时 SQLite
无真实 E:\arsm 访问
无真实 history.db 写入
可在 CI 重复执行
```

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
- [`docs/CURRENT_FUNCTIONS_REVIEW_20260628.md`](docs/CURRENT_FUNCTIONS_REVIEW_20260628.md)：2026-06-28 功能与本机历史快照
- [`WORKLOG.md`](WORKLOG.md)：历史开发记录

## License

Based on `takoyune/asmr.one-downloader` and licensed under the MIT License. See [`LICENSE`](LICENSE).
