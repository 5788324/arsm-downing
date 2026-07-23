# AI_WORKFLOW.md

# ARSM Suite AI 协作与交付工作流

> 更新时间：2026-07-23

## 1. 当前分工

### ChatGPT

负责：

- 项目架构和任务拆分；
- 主要代码开发；
- 当前环境可完成的测试；
- Git 分支、commit、PR 和审查；
- README、CURRENT_STATE、WORKLOG、路线图、决策和交接文档；
- Windows 机器证据和截图复核；
- 最终 PASS / NEEDS_FIX / BLOCKED 判断。

### Windows 本机执行者

仅负责当前环境无法覆盖的：

- Flet Desktop 窗口和鼠标交互；
- Windows 文件锁、长路径、Defender；
- 真实 ASMR.one 网络和认证；
- 便携包现场运行；
- 在线只读数据库 snapshot；
- 明确维护窗口中的受控小批量验收。

本机执行者不负责项目规划，也不自行扩大范围。

### DeepSeek / OpenCode

只在 ChatGPT 明确分配时负责：

- 低风险批量代码；
- 机械性日志收集；
- 明确脚本运行；
- 不需要视觉判断的报告整理。

DeepSeek 没有可靠视觉能力，因此：

```text
不负责 UI 美观判断
不根据截图自行给出 PASS
不使用“看起来正常”代替机器或视觉证据
```

### 用户

用户负责：

- 需求和范围决策；
- 无法远程完成时的最少点击；
- 上传本机日志、截图或证据包。

用户不负责：

```text
日常 Git
测试设计
构建
发布
逐项人工验收
```

## 2. Git 工作流

```text
一个任务 = 一个分支 + 一个 PR
本地批量修改后一个正式提交
通常一次推送
真实 CI 失败最多追加一次修复推送
禁止逐文件远程写入形成大量零碎提交
main 只接收通过测试和审查的 PR
```

分支命名：

```text
chatgpt/<task-name>
```

示例：

```text
chatgpt/t10-queue-service
```

## 3. 标准执行顺序

```text
1. 读取 CURRENT_STATE、NEXT_TASK_ROADMAP、DECISIONS 和 HANDOFF
2. 确认分支、任务边界和禁止事项
3. 本地批量修改
4. 使用临时目录、临时 SQLite 和模拟网络测试
5. 更新核心文档
6. 检查 diff、敏感路径和正式数据副作用
7. 形成一个正式 commit
8. 推送并建立 Draft PR
9. 检查 CI
10. 只把必须依赖 Windows 的部分交给本机执行者
11. 根据证据决定合并
```

## 4. 数据安全边界

项目仅供个人使用，不采用繁琐企业流程，但以下事项必须 fail-closed：

- 正式数据库写入和迁移；
- 文件移动、覆盖、隔离或删除；
- `.part` 重置或删除；
- External Intake execute；
- VACUUM；
- backlog execute；
- 资源库批量 rebuild；
- 活跃任务状态批量修改。

默认规则：

```text
dry-run 优先
正式 E:\arsm 不作为测试夹具
正式 history.db 不作为开发数据库
测试使用临时 SQLite
活跃下载存在时不升级生产环境依赖
不手工复制 WAL/SHM 作为快照
失败不得报告成功
```

## 5. Windows 验收规则

机器证据和视觉证据分开：

### 机器证据

- EXE 是否启动；
- 进程 PID；
- 正常关闭时间；
- 是否残留进程；
- 日志错误；
- 状态文件生成位置；
- 文件哈希；
- 网络状态码。

### 视觉证据

- 页面是否实际切换；
- 黑屏/白屏；
- 中文乱码；
- 控件重叠和截断；
- 缩放和布局；
- 错误提示是否可见。

规则：

```text
Kill() 不能证明正常关闭
HTTP 401 不能证明真实下载成功
没有截图的页面不能标记视觉 PASS
没有日志不能声称“无错误”
预计正常不能替代实际证据
```

## 6. 文档要求

每个任务都必须同步：

- `README.md`：面向使用和项目入口；
- `CURRENT_STATE.md`：当前事实和风险；
- `NEXT_TASK_ROADMAP.md`：可执行任务；
- `WORKLOG.md`：本轮实际完成；
- `DECISIONS.md`：新增关键决策；
- `HANDOFF.md`：下一位执行者必须知道的内容。

大型历史日志可归档到 `docs/archive/`，根文档保持可读和面向当前阶段。

## 7. 每轮交付记录

至少记录：

```text
任务范围
修改文件
测试命令和结果
是否改数据库
是否访问正式目录
是否删除或移动文件
已知限制
Git commit
PR
下一步
```

## 8. 当前任务顺序

```text
T10：Queue Service 与大队列性能
T11：Windows Desktop 视觉证据
T12：真实网络小样本和认证
T13：资源库体验
T14：可选托盘
T7：维护窗口单独执行
播放器：最后评估
```

## 9. 禁止事项

```text
不重新启用已放弃 ARSM Library v2
不把 v2 library.db 合入主线
不替换当前 200/206/416 下载核心
不在普通 UI PR 中执行真实 DB/文件迁移
不让没有视觉能力的模型审查 UI
不让用户承担可自动完成的测试或 Git 操作
```
