# ARSM Suite 项目路线图

> 更新时间：2026-07-22  
> 当前正式版本：`v0.9.0-rc.1`

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

### 阶段 A：下载器稳定化

- 断点续传、暂停、恢复、失败重试；
- HTTP 200/206/416 严格校验；
- `.part` 安全语义；
- 三通道代理和镜像切换；
- 元数据缓存和离线恢复。

### 阶段 B：资源库

- `works`、`downloads`、`library_items`、`library_index`；
- 搜索、过滤、分页和异常诊断；
- 快照式 rebuild；
- 原子索引替换；
- 陈旧索引清理。

### 阶段 C：安全事务

- External Intake 计划和冻结；
- 逐文件映射；
- 四表事务；
- staging、Journal、回滚和崩溃恢复；
- 迁移 manifest 和 post-verify。

### 阶段 D：工程和发布

- portable tests；
- Linux / Windows CI；
- 在线 SQLite 快照；
- PyInstaller one-folder；
- Windows Release workflow；
- `v0.9.0-rc.1` Pre-release。

## 当前阶段：性能与交互优化

优先顺序：

1. 下载队列 Read Model、分页、过滤和批量预览；
2. 元数据独立并发；
3. 进度检查点落库；
4. Windows 系统托盘；
5. 设置热更新；
6. 资源库详情和复制体验；
7. 状态策略和历史代码归档。

## 中期目标：0.9.0

正式版门槛：

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

在下载器和资源库稳定后再进入 MVP：

- 播放、暂停、上一首、下一首；
- 播放进度；
- 恢复上次位置；
- 本地音轨列表；
- 后续 LRC 和转录集成。

### T7 真实目录整理

必须等待维护窗口：

- 活跃任务自然清空；
- 完整备份；
- 1~3 个无争议作品；
- dry-run、执行、post-verify 和回滚证据。

## 永久原则

```text
SQLite 是唯一业务真源
LibraryVault 是正式数据库入口
UI 不直接访问 SQLite
真实文件操作必须 dry-run
失败不得伪报成功
优化不得破坏旧任务恢复
```
