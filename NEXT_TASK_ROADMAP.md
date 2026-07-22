# ARSM Suite 当前详细任务路线图

> 更新时间：2026-07-22
> 基线：`main@9f292e7947804f2e4d53290039501f79c6d1805d`
> 当前发布：`v0.9.0-rc.1`
> 当前分支：`chatgpt/optimize-o1-20260722`
> 当前 PR：`#6`
> 当前阶段：`O1 下载队列与调度优化`

## 总原则

```text
不推倒重写
不迁移旧数据库
不改变现有任务路径
不把托盘、调度和设置热更新混成一个 PR
一个任务包 = 一个分支 + 一个 PR
本地批量修改，形成原子提交
真实 CI 失败最多一次修复推送
```

## O0：RC1 发布和仓库清理

- [x] PR #1 Squash Merge 到 `main`
- [x] 创建 `v0.9.0-rc.1`
- [x] Windows Release workflow PASS
- [x] 发布 ZIP 与 SHA-256
- [x] 清理旧本地和远端分支
- [x] 删除废弃 v2、验收和旧构建目录
- [x] 正式环境零接触
- [ ] Codex提交最终 Windows 现场验收报告

## O1：下载队列与调度优化

目标版本：`0.9.0-rc.2`

### O1-A：只读模型和批量预览

- [x] `DownloadTaskSnapshot`
- [x] `DownloadQueueSummary`
- [x] `DownloadQueuePage`
- [x] 聚合 `works + downloads`
- [x] 保留 orphan downloads 可见性
- [x] 终态作品屏蔽历史 paused/failed 干扰
- [x] `registered` 计入完成
- [x] 独占状态和有界分页
- [x] 批量 RJ 规范化、去重和分类
- [x] 一次有界已知作品查询

### O1-B：下载页 UI

- [x] DownloadView 接入 Read Model
- [x] 工作中、活动、等待、暂停、失败、完成和全部过滤
- [x] 默认隐藏已完成任务
- [x] 每页 24 项
- [x] 上一页、下一页、页码和刷新
- [x] `DownloadQueueSummary` 总览
- [x] 卡片使用 Snapshot 标题、路径、封面和聚合进度
- [x] 屏外任务不重建控件
- [x] 后台刷新失败恢复 UI 状态
- [x] 批量输入预览确认
- [x] 删除初始加载的逐卡片数据库查询路径

### O1-C：独立元数据并发

- [x] `metadata_concurrency`
- [x] 默认值 2，限制 1~8
- [x] 独立 metadata Semaphore
- [x] 元数据不占用音频文件槽
- [x] 设置页和示例配置
- [x] work / metadata / file 并发日志
- [x] 并发峰值单元测试
- [ ] 后续设置热更新在 O3 完成，不在本 PR 强行重建活跃 Semaphore

### O1-D：进度持久化审计

- [x] 审计 `download_file()` SQLite 写入点
- [x] 实时速度、ETA、当前字节保留内存
- [x] 禁止每个下载 chunk 写 SQLite
- [x] 文件开始写 `downloading` 检查点
- [x] 暂停、失败、完成和退出保留持久化
- [x] `.part` 继续作为恢复字节数最终依据
- [x] 写入频率回归测试

### O1-E：自动验收

- [x] `compileall`
- [x] 本地隔离测试：220 passed
- [ ] PR #6 Ubuntu / Python 3.10 CI
- [ ] PR #6 Windows / Python 3.12 CI
- [ ] 真实 Flet 0.27.6 import 和 UI 语义
- [ ] Windows Artifact 构建
- [ ] Codex 队列筛选、分页、批量预览、暂停和恢复验收

### O1 发布门槛

```text
数据库 schema 不变
旧任务 local_path 不变
旧 .part 不删除
工作中页面默认不显示 completed
100+ 混合任务队列查询无明显卡顿
批量预览确认前零副作用
portable tests 全绿
Windows UI、暂停、重启恢复通过
```

## O2：Windows 系统托盘

单独分支和 PR：

- [ ] 关闭窗口时最小化到托盘 / 直接退出
- [ ] 打开窗口、暂停全部、继续全部、彻底退出
- [ ] 复用幂等 shutdown
- [ ] PyInstaller 图标和 hidden imports
- [ ] Explorer 重启恢复策略
- [ ] 无残留进程实机验收

## O3：设置热更新

单独分支和 PR：

- [ ] API 和代理 URL 验证
- [ ] 保留原子保存
- [ ] 保存成功后应用到未来请求
- [ ] 活跃任务保持原连接
- [ ] 应用失败恢复旧设置
- [ ] 重建 metadata/work/file 并发资源的明确时机

## O4：资源库详情体验

- [ ] 异步详情
- [ ] 超大列表截断提示
- [ ] 路径可选择复制
- [ ] 复制 RJ 和目录
- [ ] 打开目录统一错误
- [ ] 不在 UI 线程递归扫描磁盘

## O5：状态策略与历史整理

- [ ] `WorkStatePolicy`
- [ ] 合法转换集中校验
- [ ] 不立即迁移历史状态
- [ ] 统一 DB 状态和 UI 文案
- [ ] 归档重复历史测试脚本
- [ ] 更新文档索引

## 继续冻结

- External Intake 正式 Execute
- 正式迁移和隔离
- 正式 VACUUM
- backlog execute
- T7 目录整理
- 对现有任务的批量状态或路径修改

## 发布策略

```text
0.9.0-rc.1：当前正式观察版本
0.9.0-rc.2：O1 下载队列、Read Model、批量预览和调度
0.9.0-rc.3：O2 托盘与 O3 设置热更新（按风险可拆）
0.9.0：真实下载、长期运行、暂停恢复和退出稳定
播放器：后续版本
```
