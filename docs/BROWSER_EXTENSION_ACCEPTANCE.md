# ARSM 浏览器扩展验收记录

> 日期：2026-08-19
> 分支：`codex/asmr-browser-extension`
> 基线：`cc41d94`
> 结论：代码门禁通过，Chrome/Edge 人工安装矩阵待完成

## 已完成

- 本机桥接仅监听 `127.0.0.1:17641`，要求固定扩展 ID、扩展 Origin 和随机令牌；
- 接口覆盖健康检查、批量状态、单任务状态、入队和打开 ARSM 页面；
- 返回数据只包含 RJ、业务状态和安全布尔值，不包含绝对路径、Cookie 或数据库对象；
- Manifest V3 扩展只声明 `storage` 和本机桥接 host permission；
- 列表卡片批量标记，详情页优先在“销量”区域注入状态与下载按钮；
- MutationObserver、轮询恢复、重复注入防护和多标签重复入队由桥接与核心队列双重阻断；
- ARSM 设置页可启停桥接、查看端口/扩展 ID/令牌、打开安装目录、检查连接、重新生成令牌并打开卸载管理页；
- PyInstaller spec 已包含 `browser_extension/`。

## 自动化证据

```text
浏览器桥接、扩展契约、配置、设置页、关机：39 passed
完整 portable pytest：397 passed, 3 skipped
跳过原因：当前 Windows 环境不可创建符号链接
JavaScript 语法：shared/service-worker/content/options 全部 PASS
Python compileall：PASS
git diff --check：PASS
```

完整回归使用仓库外临时目录，未读取或修改真实媒体库。

## 当前站点结构核对

侧边浏览器只读打开了：

```text
https://asmr.one/works
https://asmr.one/work/RJ01651727
```

观察结果：

- 列表存在 `.q-card.fit` 卡片和 `/work/RJ...` 链接，RJ 提取规则匹配；
- 详情标题为 `H1`；
- 详情销量文本为 `销量: 1797`，位于 `.q-pt-sm.q-pb-none` 区域；
- 内容脚本已按该结构优先把标签和按钮放到销量区域；找不到销量时才安全回退到标题/卡片区域。

## Windows 应用界面核对

使用 `C:\tmp\arsm-browser-ext-profile` 隔离 Profile 启动源码版 ARSM Suite：

- 设置页正常打开，无黑屏；
- “浏览器扩展”标题和说明在正常滚动流中可见；
- 真实媒体库未加载；
- 本轮启动的临时 Python/Flet 进程已结束。

## 待人工验收

浏览器安全策略不允许应用静默安装或卸载扩展。以下项目必须在用户确认安装后执行，当前不得写成 PASS：

- Chrome 稳定版加载未打包扩展；
- Edge 稳定版加载未打包扩展；
- 扩展设置页粘贴隔离 Profile 的令牌并检查连接；
- 列表、搜索、分页/无限滚动、详情页的视觉位置与点击；
- 100% / 125% / 150% 缩放及深浅外观；
- 多标签快速点击、ARSM 退出/重启和扩展卸载；
- 使用临时/小样本数据库验证完整状态矩阵。

## 数据保护

```text
真实 E:\arsm 读取：未执行
真实媒体删除：无
真实媒体移动或重命名：无
真实媒体覆盖：无
```
