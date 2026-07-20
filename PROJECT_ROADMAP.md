# PROJECT_ROADMAP.md

# arsm-downing / arsm-suite 下一阶段执行路线图

> **状态说明（2026-07-20）**：本文件保留中长期产品路线和历史阶段。当前开发事实、优先级和可执行任务以 `CURRENT_STATE.md` 与 `NEXT_TASK_ROADMAP.md` 为准。播放器暂不进入当前稳定性修复范围。

## 0. 当前方向

本项目继续作为一个单一 Flet 个人应用推进，不拆成多个独立项目。

```text
arsm-downing / arsm-suite
├── downloader 下载模块
├── library 资源库管理模块
├── player 播放模块
├── migration 迁移模块
└── LibraryVault 统一 SQLite 访问层
```

当前阶段继续使用：

```text
Python + Flet + SQLite + asyncio + LibraryVault
```

长期目标可以是一个本地个人媒体库，但当前阶段不跳到完整媒体库开发。当前优先顺序是：

```text
1. external intake 真实执行硬冻结（已完成）
2. external intake 固定计划模型与纯扫描收口
3. 下载核心 416 / Range / `.part` / 取消恢复修复
4. 数据库 Schema 与资源库一致性
5. UI、迁移和 backlog 稳定性修复
6. 统一测试、CI、Windows 验收后再评估播放器
```

---

## 1. 核心原则

### 1.1 SQLite 是唯一真源

```text
history.db / SQLite = 唯一真源
LibraryVault = 唯一 DB 访问入口
P3 JSON report = 只读诊断报告
manifest.json = 后续可选导出/缓存
```

禁止：

```text
把 P3 扫描 JSON 当成 P6 UI 数据源
把 manifest.json 当成主数据源
让 UI 绕过 LibraryVault 直接读写 SQLite
让新模块自己 LibraryVault()
让新模块自己 sqlite3.connect()
```

### 1.2 文档跟随事实，不代替事实

遇到以下问题时：

```text
要不要重构
够不够安全
状态是否可信
DB 是否有脏数据
是否可以继续扩展
```

优先顺序必须是：

```text
1. 直接看代码
2. 跑只读诊断脚本
3. 看输出结果
4. 再写结论和任务
```

### 1.3 不合并不同性质的 DB 写入

禁止一次任务同时做：

```text
修 downloads / works 状态
写 library_items / library_files 索引
改 UI
改下载核心
删除文件
```

尤其注意：

```text
P4 的 RC9 安全修复 和 P5 的资源库索引入库 必须分开执行。
```

---

## 2. 总阶段顺序

```text
P1：UI 侧 LibraryVault 单例确认
P2：RC9 下载状态只读诊断
P3：资源库只读扫描 MVP
P4：RC9 安全修复第一轮
P4.5：library_items schema 决策
P5：资源库索引入库
P6：资源库管理 UI MVP
P7：播放器 MVP
P8：媒体库体验打磨
```

说明：

```text
P0（RC8.7 final audit）已完成，不再作为下一步待执行项。
```

---

## 3. 当前现实目标

```text
1. 确认整个 Flet 应用只创建一个 LibraryVault 实例
2. 解释 failed / paused / registered / prepared 等状态
3. 扫描 E:\arsm 并产出只读资源库报告
4. 在写入资源库索引前确定 library_items schema
```

当前不要做：

```text
完整播放器
漂亮媒体库 UI
Web 管理器
OpenList 深度集成
LRC/转录完整集成
下载器大重构
DB 大重构
```

---

## 4. P1：UI 侧 LibraryVault 单例确认

### 目标

确认整个 Flet 应用只创建一次 `LibraryVault()`。

### 任务

```text
1. grep LibraryVault(
2. grep sqlite3.connect
3. 检查 main.py / ui/app.py / 启动初始化文件
4. 检查 DownloadView / ToolsView / LibraryView 是否自己创建 DB
5. 如果只有单实例，记录到 WORKLOG
6. 如果发现多实例，先停止后续开发，做最小收口
```

### 建议安全网

可在 `LibraryVault.__init__` 中加入多实例 warning，但这是可选优化，不是当前阶段必做项。

---

## 5. P2：RC9 下载状态只读诊断

### 目标

解释 `failed / paused / registered / prepared` 等状态。只读，不修 DB。

### 任务

```text
1. 统计 works_status
2. 统计 downloads_status
3. failed 按 error prefix 分类
4. paused 按文件存在状态分类
5. registered 按真实待下载/历史残留分类
6. 重点 RJ 单独诊断
7. 检查异常 RJ 号
8. 检查 normalize_rj_id 是否覆盖所有写入入口
```

重点 RJ：

```text
RJ01588893
RJ01534605
RJ00323125
RJ323125
missing_work_paths 几项
```

### 输出

```text
RC9_DOWNLOAD_STATUS_DIAGNOSIS.json
RC9_DOWNLOAD_STATUS_DIAGNOSIS_SUMMARY.txt
```

### 禁止

```text
不改 DB
不删文件
不移动文件
不重新下载
不批量重置状态
```

---

## 6. P3：资源库只读扫描 MVP

### 目标

扫描 `E:\arsm`，输出只读资源库报告。不写 DB，不接 UI。

### 任务

```text
1. 扫描 E:\arsm
2. 识别 RJ 目录
3. 识别非 RJ 目录
4. 分类 audio / video / image / subtitle / text / archive / other
5. 统计每个作品文件数
6. 统计每个作品总大小
7. 找封面候选
8. 找音频候选
9. 找字幕/LRC 候选
10. 输出 JSON report
11. 输出 summary
```

### 输出

```text
library_scan_report.json
library_scan_summary.txt
```

### 关键规则

```text
P3 JSON 只是给人看的诊断报告。
P3 JSON 不进入 P6 UI 数据路径。
P6 UI 必须通过 LibraryVault / SQLite 获取数据。
```

---

## 7. P4：RC9 安全修复第一轮

### 目标

基于 P2 诊断结果，只修确定安全的问题。

### 可修类型

```text
最终文件存在且大小匹配，但 DB 状态不是 completed
work 已完成但 downloads 状态滞后
RJ 号历史脏数据且映射唯一
local_path 明确可修正且目标存在
```

### 不修类型

```text
缺文件
路径不确定
大小不匹配
URL 不确定
metadata 缺失
RJ 号映射不唯一
旧路径不存在且目标也不存在
pending_user_review
```

### 禁止

```text
不批量全库 update
不猜路径
不根据标题模糊匹配修 DB
不删除文件
不与 P5 资源库索引入库合并执行
```

---

## 8. P4.5：library schema 决策

### 结论

```text
library_index：保留为位置/迁移/扫描发现索引
library_items：新建，作为 P6 UI 的作品级资源库索引
library_files：后续需要文件详情/播放器时再建
```

### 必须回答

```text
1. 是否新建 library_items：是
2. 是否复用 library_index：否，不硬塞内容索引字段
3. library_items 是否作为 P6 UI 主数据源：是
4. P3 JSON 是否作为 P6 UI 主数据源：否
5. library_files 是否第一版创建：否
```

---

## 9. P5：资源库索引入库

### 目标

把 P3 扫描结果写入 SQLite 的 `library_items`，供 P6 UI 使用。

### 写入范围

```text
P5 只写 library_items
P5 不写 works / downloads / library_index / download status
```

---

## 10. P6：资源库管理 UI MVP

### 第一版功能

```text
作品列表
RJ 搜索
标题搜索
封面显示
文件数/大小显示
状态标签
异常提示
打开文件夹
刷新资源库索引
```

### 数据源规则

P6 UI 必须通过 `LibraryVault / SQLite` 获取数据。

禁止在 `ui/library_view.py` 或相关 UI 文件中出现：

```python
open("library_scan_report.json")
json.load(...)
sqlite3.connect(...)
LibraryVault()
```

---

## 11. P7：播放器 MVP

### 第一版功能

```text
播放音频
暂停
继续
上一首
下一首
显示当前音轨
显示播放进度
保存播放进度
恢复上次播放位置
```

### 首选方案

先试 Flet audio。

### 放弃信号

命中以下任一情况则转向 `python-vlc` 或 `mpv`：

```text
1. 拿不到精确播放位置回调
2. seek / 切歌明显卡顿
3. 长时间播放超过 10 分钟后内存增长或崩溃
4. 不支持资源库中常见格式，例如 flac / ogg
```

---

## 12. P8：媒体库体验打磨

P8 是后期目标，不属于当前执行范围。

相关 UI/UX 灵感统一放入：

```text
docs/IDEAS_BACKLOG.md
```

---

## 13. AI 工具分工

### Codex

```text
最终审查
Git 合并
RC closeout 判断
DB 风险判断
关键小改动
```

### OpenCode + DeepSeek

```text
诊断脚本
scanner MVP
pytest
JSON 报告
低风险代码实现
```

### Claude / ChatGPT / Hermes

```text
架构判断
规划
文档整理
风险审查
```

---

## 14. 当前最重要的一句话

```text
当前阶段不追求完整媒体库；先完成 P1/P2/P3/P4.5。SQLite 仍是唯一真源，LibraryVault 是唯一 DB 入口，P3 JSON 不进入 UI 数据路径，P4 下载状态修复和 P5 资源库索引入库必须分开执行。
```
