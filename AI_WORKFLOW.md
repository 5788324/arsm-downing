# AI_WORKFLOW.md

# arsm-downing / arsm-suite 简化 AI 工作流

## 0. 当前结论

本项目后续采用最简协作模式：

```text
用户 + ChatGPT + DeepSeek/OpenCode 为主
Codex 作为本机关键节点工具和最终保险
```

不采用复杂多层代理链路：

```text
ChatGPT → Codex → DeepSeek → Codex → 用户
```

采用：

```text
ChatGPT：规划、拆任务、验收标准
DeepSeek/OpenCode：日常执行、写代码、跑脚本、生成报告
Codex：本机关键节点、最终审查、Git、危险操作前把关
用户：复制一轮任务、运行工具、把结果贴回 ChatGPT
```

补充当前事实：

```text
RC8.7 P0 final audit 已由 Codex 在本机完成。
后续 DeepSeek/OpenCode 不需要重做 RC8 迁移，只需从 P1 / P2 / P3 往后推进。
```

---

## 1. 角色定位

### 1.1 用户

用户是最终决策人，但不需要看懂所有代码。

用户只做：

```text
1. 把 ChatGPT 给出的任务复制给 DeepSeek/OpenCode 或 Codex
2. 运行工具
3. 把 DeepSeek/OpenCode/Codex 的结果贴回 ChatGPT
4. 根据 ChatGPT 的 PASS / NEEDS_FIX / STOP 继续下一步
```

### 1.2 ChatGPT

ChatGPT 是项目经理，负责：

```text
1. 定阶段
2. 拆任务
3. 写可直接执行的任务
4. 写禁止事项
5. 写验收标准
6. 看执行结果
7. 判断 PASS / NEEDS_FIX / STOP
8. 决定什么时候需要 Codex
```

### 1.3 DeepSeek / OpenCode

DeepSeek/OpenCode 是主力执行工人。

优先交给它们的任务：

```text
1. 只读审计
2. grep / 搜索
3. 写诊断脚本
4. 写 scanner
5. 生成 JSON 报告
6. 写 summary
7. 更新 WORKLOG
8. 低风险代码实现
```

禁止：

```text
1. 未经确认删除文件
2. 未经确认修改 DB
3. 绕过 LibraryVault
4. 自己 sqlite3.connect
5. 把 P3 JSON 当 UI 数据源
6. 把 P4 和 P5 合并执行
7. 顺手重构下载核心
8. 顺手改 database.py 写入核心
9. 顺手改 migration cleanup
```

每轮完成后必须输出：

```text
1. 完成了什么
2. 修改了哪些文件
3. 是否改 DB
4. 是否删除文件
5. 是否改下载核心
6. 生成了哪些报告
7. 测试/核验结果
8. git status
9. git diff summary
10. WORKLOG 更新位置
11. 下一步建议
```

### 1.4 Codex

Codex 不再作为日常执行者。

Codex 的定位：

```text
本机关键节点工具
最终保险
Git 守门员
高风险操作前审查员
```

Codex 只在这些情况使用：

```text
1. 需要直接控制本机文件，而 ChatGPT 无法操作时
2. 要 commit / merge / push 前
3. 要执行 DB 写入前
4. 要执行文件删除前
5. 要修改下载核心前
6. 要修改 database.py 写入核心前
7. DeepSeek/OpenCode 改动较大，需要本机二次审查时
8. Git 状态复杂、冲突、误提交风险时
```

Codex 输出必须明确：

```text
PASS
NEEDS_FIX
STOP
```

---

## 2. 为什么 Codex 仍然需要保留

ChatGPT 不能控制你的电脑，所以以下场景仍然需要 Codex：

```text
1. 看真实 git diff
2. 检查本地文件实际状态
3. 检查项目目录是否干净
4. 确认是否误删/误改
5. 执行 commit / push
6. 做危险操作前最后确认
```

---

## 3. 当前推荐流程

### 3.1 日常低风险任务

适用：

```text
只读诊断
grep
生成报告
scanner
普通文档更新
低风险代码
```

流程：

```text
1. ChatGPT 写一轮 DeepSeek/OpenCode 任务
2. 用户复制给 DeepSeek/OpenCode
3. DeepSeek/OpenCode 执行
4. 用户把结果贴回 ChatGPT
5. ChatGPT 判断 PASS / NEEDS_FIX / STOP
6. 只有必要时再叫 Codex
```

### 3.2 高风险任务

适用：

```text
DB 写入
删除文件
修改下载核心
修改 database.py 写入核心
migration cleanup
commit / push
```

流程：

```text
1. ChatGPT 写任务和风险边界
2. DeepSeek/OpenCode 先生成 dry-run / plan
3. 用户贴回 ChatGPT
4. ChatGPT 判断是否需要 Codex
5. Codex 做本机最终审查
6. 用户确认后才执行
```

---

## 4. 当前最小文件体系

正式保留：

```text
PROJECT_ROADMAP.md
WORKLOG.md
AI_WORKFLOW.md
```

不强制新增：

```text
AGENTS.md
.local_tasks/
复杂任务模板
多代理配置
MCP
自动调用 OpenCode 的脚本
```

---

## 5. 当前下一步建议

推荐顺序：

```text
1. DeepSeek/OpenCode：执行 P1 LibraryVault 单例确认
2. DeepSeek/OpenCode：执行 P2 RC9 下载状态只读诊断
3. 用户把报告贴回 ChatGPT
4. ChatGPT 判断是否需要 Codex 审查
5. 如 P1/P2 通过，再进入 P3/P4.5
```

Codex 是否必须再次执行 P0？

```text
不必须。
```

只有在以下情况下才需要重开 P0：

```text
1. 有人怀疑 RC8.7 审计结果不真实
2. 本机文件/DB 状态在 P0 之后又发生变化
3. 出现 missing_completed_download_paths > 0
4. 出现 allowlist target 漂移
```

---

## 6. 当前本机摘要

```text
RC8.7 final audit report:
.local_backups/rc8_7_final_audit_20260627_101934/RC8_7_FINAL_MIGRATION_CLOSEOUT_REPORT.txt

关键结果：
- integrity_check = ok
- missing_completed_download_paths = 0
- resource_scan_errors = 0
- allowlist_not_on_e_count = 0
- RC8 migration phase closeout = yes

已知残留交给 RC9：
- works_completed_verified_not_on_E = 17
- downloads_completed_not_on_E_grouped_count = 2
- missing_work_paths_count = 3
- 重点 RJ：RJ01588893 / RJ01534605 / RJ00323125 / RJ323125
```

---

## 7. 给 DeepSeek/OpenCode 的通用复制指令

```text
请先读取 PROJECT_ROADMAP.md、WORKLOG.md、AI_WORKFLOW.md。

本轮执行：<写当前阶段任务，例如 P1：LibraryVault 单例确认 或 P2：RC9 下载状态只读诊断>。

严格遵守：
1. 不扩大范围
2. 不删除文件
3. 未经确认不修改 DB
4. 不绕过 LibraryVault
5. 不改下载核心
6. 完成后更新 WORKLOG.md

完成后输出：
1. 修改文件列表
2. 是否改 DB
3. 是否删除文件
4. 是否改下载核心
5. 生成报告路径
6. 测试/核验结果
7. git status
8. git diff summary
9. 下一步建议
```

---

## 8. 给 Codex 的通用复制指令

```text
请先读取 PROJECT_ROADMAP.md、WORKLOG.md、AI_WORKFLOW.md。

你现在是本机审查员，不要实现新功能。

请检查当前 git diff、输出报告和工作目录状态，判断本轮是否安全。

重点检查：
1. 是否违反阶段边界
2. 是否误改 DB
3. 是否删除文件
4. 是否绕过 LibraryVault
5. 是否直接 sqlite3.connect
6. 是否改下载核心
7. 是否改 database.py 写入核心
8. 是否把 P3 JSON 当 UI 数据源
9. 是否把 P4 和 P5 合并执行
10. WORKLOG 是否更新

最后只给明确结论：
PASS / NEEDS_FIX / STOP
```

---

## 9. 一句话总结

```text
日常由 ChatGPT 指挥 DeepSeek/OpenCode 干活；Codex 不再日常参与，只在需要本机控制、最终审查、commit、DB 写入、删除文件、修改核心模块时作为保险使用。当前 P0 已完成，后续从 P1 / P2 开始推进即可。
```
