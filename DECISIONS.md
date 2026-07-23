# ARSM Suite 关键决策记录

## D-20260723-01：现有主线和数据库继续使用

```text
history.db / SQLite = 唯一业务真源
LibraryVault = 唯一正式数据库入口
main = 唯一产品主线
```

禁止新建第二套正式 `library.db`、替换下载表或让 UI 直接连接 SQLite。

## D-20260723-02：放弃 ARSM Library v2

`ARSM-Library-v2-source-20260722` 不继续、不合并、不替代当前版本。

只吸收：

- Service/read model；
- 批量队列快照；
- metadata/audio 队列分离；
- 批量添加预览；
- 显式状态迁移；
- 页面生命周期；
- 资源库详情；
- 后续托盘概念。

不吸收新数据库、v2 下载引擎、非原子设置保存、正式库直入和整套未验收 UI。

## D-20260723-03：T10 只做低风险内部优化

```text
不改数据库 schema
不替换下载核心
不改 .part
不访问正式数据
不加入托盘
不开发播放器
```

## D-20260723-04：机器验收与视觉验收分开

- 本机执行者返回启动、PID、日志、文件、哈希和截图；
- ChatGPT 判断视觉；
- `Kill()` 不证明正常关闭；
- 401 不证明下载成功；
- DeepSeek 不负责视觉 PASS。

## D-20260723-05：正式维护操作继续冻结

现有混合任务清空或进入维护窗口前，冻结 External Intake execute、正式迁移、VACUUM、backlog execute 和 T7。

## D-20260723-06：播放器继续延后

播放器排在 T10~T14 之后。开始前必须先完成大队列性能、Desktop 证据和真实下载路径收口。

## D-20260723-07：工作日志分段归档

旧工作日志保存在：

```text
docs/archive/WORKLOG_20260627_20260721.md
```

根 WORKLOG 只记录 Post-RC 阶段。

## D-20260723-08：活动下载队列只显示非终态作品

### 决策

下载中心是活动队列，不是历史列表。

```text
queued / downloading / paused / failed / resuming：显示
completed / registered / verified / external / indexed：隐藏
```

作品完成后立即从活动队列移除；历史仍保存在 SQLite 和资源库。

### 原因

- 完成项留在队列会淹没当前任务；
- 资源库和历史数据库已经负责完成记录；
- 旧延迟清理依赖后续 progress 事件，最后一个任务完成后可能永远不触发。

## D-20260723-09：批量按钮保留并明确语义

### 决策

保留两个按钮：

```text
全部暂停
全部继续
```

“全部开始”改为“全部继续”，因为它恢复 paused/queued/可重试任务，而不是重新创建全部任务。

### UI 规则

- 没有 queued/downloading 时禁用“全部暂停”；
- 没有 paused/failed 时禁用“全部继续”；
- 批量动作结束后只进行一次 SQLite 队列重载；
- 汇总显示作品数和全局总速度。

## D-20260723-10：删除统计与成就页面

### 决策

删除 Dashboard/“统计与成就”页面和完成后的成就触发。

### 兼容

旧 `config.json` 中的 `achievements` 字段暂时保留读取，避免无必要的配置迁移；应用不再展示或新增成就。
