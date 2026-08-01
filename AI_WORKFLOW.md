# ARSM Suite AI 协作流程

## 当前分工

```text
ChatGPT：只读 GitHub、架构、主要开发、本地测试、文档、代码审查、交付包
Codex：拉取 Git、应用交付包、Windows/Flet/构建/真实网络、最终 Git 推送和 PR
用户：需求和范围决策，不负责 Git、测试、构建或发布
```

## Git 规则

- ChatGPT 不推送远端；
- 一个任务 = 一个分支 + 一个 PR；
- Codex 从最新 main 建分支；
- 本地批量修改后一个正式 commit；
- 通常一次 push；真实 CI 失败最多一次修复 push；
- 禁止逐文件远程提交和临时补丁工作流；
- main 只接收测试与实机证据通过的 PR。

## 安全规则

- 测试只用临时 SQLite、临时目录和 fake server；
- 正式 `history.db`、`config.json`、`queue.json`、WAL/SHM 和 `E:\arsm` 不进入开发测试；
- `.part` 不手工删除或重置；
- 文件移动和数据库批量写入必须独立任务、dry-run 和可恢复；
- 没有证据不得报告 PASS。

## 验收分工

- Codex 采集机器事实、日志、截图和哈希；
- ChatGPT 负责视觉复核、代码修复判断和最终结论；
- DeepSeek 不负责视觉判断；
- `Kill()` 不证明正常关闭；
- HTTP 401 不证明真实下载成功。
