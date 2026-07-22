# ARSM Suite 项目路线图

> 更新时间：2026-07-22
> 当前正式版本：`v0.9.0-rc.1`
> 当前开发目标：`v0.9.0-rc.2`

## 产品定位

ARSM Suite 保持为一个个人本地 Windows 单体应用：

```text
下载器
资源库
安全迁移与 External Intake
系统工具
后续播放器
```

技术主线保持：

```text
Python + Flet + SQLite + asyncio + aiohttp + LibraryVault
```

## 已完成阶段

### A. 下载器稳定化

- 断点续传、暂停、恢复、重连和失败重试；
- HTTP 200/206/416 严格校验；
- `.part` 安全语义；
- 三通道代理、镜像切换和元数据缓存。

### B. 资源库

- `works`、`downloads`、`library_items`、`library_index`；
- 搜索、过滤、分页和异常诊断；
- 快照式 rebuild、原子索引替换和陈旧索引清理。

### C. 安全事务

- External Intake 计划和真实入口冻结；
- 逐文件映射、四表事务、staging、Journal 和回滚；
- 迁移 manifest、post-verify 和失败恢复。

### D. 工程与发布

- portable tests 和 Linux / Windows CI；
- 在线 SQLite 快照；
- PyInstaller one-folder；
- Windows Release workflow；
- `v0.9.0-rc.1` Pre-release。

## 当前阶段：O1 性能与交互优化

O1 已实现：

1. 下载队列统一 Read Model；
2. 有界聚合查询，消除实际队列渲染 N+1；
3. 状态过滤、分页和默认隐藏完成；
4. 批量 RJ 预览、去重、查重和确认；
5. 独立元数据并发池；
6. 实时进度内存化与 SQLite 检查点写入；
7. 对旧任务、旧路径和旧 `.part` 零迁移。

当前剩余：PR CI、Windows Artifact 和 Codex 实机验收。

## 后续阶段

### O2：Windows 系统托盘

- 关闭到托盘 / 直接退出；
- 打开、暂停全部、继续全部、彻底退出；
- PyInstaller 和 Explorer 恢复；
- 无残留进程。

### O3：设置热更新

- API/代理验证；
- 原子保存；
- 未来请求应用；
- 活跃连接不强制中断；
- 失败回退。

### O4：资源库详情

- 异步详情；
- 超大列表截断；
- 路径/RJ 复制；
- 统一错误提示。

### O5：状态策略与历史整理

- `WorkStatePolicy`；
- 状态转换集中校验；
- 历史脚本归档；
- 文档索引整理。

## 正式 0.9.0 门槛

- 真实 ASMR.one 下载稳定；
- 暂停、退出、重启和恢复不丢断点；
- 100+ 混合任务 UI 可用；
- 长时间运行无明显泄漏；
- 托盘与彻底退出稳定；
- Windows Defender 和文件占用行为可解释；
- 高风险工具继续 fail-closed。

## 后续方向

### 新任务暂存模式

仅作用于新任务，不迁移旧任务：

- 当前输出目录；
- 独立下载暂存区；
- 正式资源库根目录。

### 播放器

下载器和资源库稳定后再进入 MVP：播放、暂停、切歌、进度和恢复位置；后续再考虑 LRC 和转录。

### T7 真实目录整理

必须等待活跃任务清空、完整备份和明确维护窗口，只选 1~3 个无争议作品完成 dry-run、执行、post-verify 和回滚证据。

## 永久原则

```text
SQLite 是唯一业务真源
LibraryVault 是正式数据库入口
UI 不直接访问 SQLite
真实文件操作必须 dry-run
失败不得伪报成功
优化不得破坏旧任务恢复
```
