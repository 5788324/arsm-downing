# ARSM Suite 交接说明

> 更新时间：2026-07-23

## 当前版本

```text
已发布：0.9.0-rc.1
开发候选：0.9.0-rc.2
当前任务：T9.1 下载页现场缺陷修复
下一任务：T10 Queue Service 与大队列性能
```

## 已验证事实

- `0.9.0-rc.1` 已合并并完成 Linux/Windows CI；
- 原基线 205/205 tests；
- Windows one-folder Release 可启动；
- Windows 11 连续三次启动和正常关闭通过；
- 真实 ASMR.one 元数据、tracks、`.part`、暂停、重启、恢复和最终 MP3 已验证；
- 全部暂停和全部开始的核心逻辑实际有效；
- 正式 `history.db`、`E:\arsm` 和现有任务未被开发环境修改。

Windows 报告发现底部汇总在批量恢复后不刷新。该问题在 `0.9.0-rc.2` 修复。

## T9.1 改动

- 批量动作结束后通过 UI queue 请求一次 SQLite 队列重载；
- 汇总显示作品状态和实时总速度；
- 卡片显示作品速度；
- 完成项立即移出活动队列；
- “全部开始”改为“全部继续”；
- 按钮按当前可执行状态禁用；
- 删除 Dashboard/统计与成就页面；
- 保留旧 achievements 配置字段兼容读取；
- 版本升级到 `0.9.0-rc.2`。

本地结果：

```text
compileall：PASS
portable tests：211/211 PASS
```

本地 UI 测试使用临时 Flet 接口桩；必须等待 GitHub Linux/Windows CI 使用真实 Flet 0.27.6。

## 下一位 AI 的顺序

1. 核对 T9.1 PR CI；
2. CI 通过后合并；
3. 不再重复修下载页旧汇总；
4. 创建 `TAKEOVER-T10` 独立分支；
5. 先做 read model + 批量快照，再做 metadata queue；
6. 批量 RJ 预览必须明确解释重复、已存在和无效项。

## T10 边界

```text
不改数据库表结构
不替换下载核心
不改 200/206/416 和 .part
不访问正式 history.db 或 E:\arsm
不加入托盘
不开发播放器
```

## 继续冻结

```text
External Intake execute
正式资源库迁移/移动/隔离/删除
正式 VACUUM
正式 backlog execute
T7 正式目录整理
覆盖仍在下载的正式程序目录
```

## Windows 验收分工

- ChatGPT 负责验收设计、代码审查和视觉判断；
- 本机执行者只在隔离目录运行并返回原始证据；
- DeepSeek 不自行判断视觉 PASS；
- 用户不负责 Git、测试设计、构建或发布。
