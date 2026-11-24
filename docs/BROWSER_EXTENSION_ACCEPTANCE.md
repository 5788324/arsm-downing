# ARSM 浏览器扩展验收记录

> 初始记录：2026-08-19
> 最终复核：2026-08-30
> 分支：`codex/asmr-browser-extension`
> 基线：`cc41d94`
> 结论：`PASS WITH NOTES`；自动门禁、Edge/Chrome 双域名实机、隔离入队/去重/状态回写、断线恢复、缩放/外观和卸载均通过

## 已完成

- 本机桥接仅监听 `127.0.0.1:17641`，要求固定扩展 ID、受控扩展 Origin 和随机令牌；兼容 Chromium MV3 后台请求的 opaque `Origin: null`，但仍同时校验固定扩展 ID 与强令牌；
- 接口覆盖健康检查、批量状态、单任务状态、入队和打开 ARSM 页面；
- 返回数据只包含 RJ、业务状态和安全布尔值，不包含绝对路径、Cookie 或数据库对象；
- Manifest V3 扩展只声明 `storage` 和本机桥接 host permission；
- 列表卡片批量标记，详情页优先在“销量”区域注入状态与下载按钮；
- MutationObserver、轮询恢复、重复注入防护和多标签重复入队由桥接与核心队列双重阻断；
- ARSM 设置页可启停桥接、查看端口/扩展 ID/令牌、打开安装目录、检查连接、重新生成令牌并打开卸载管理页；
- PyInstaller spec 已包含 `browser_extension/`。

## 自动化证据

```text
浏览器桥接与扩展契约聚焦回归：21 passed
完整 portable pytest：411 passed, 3 skipped
跳过原因：当前 Windows 环境不可创建符号链接
JavaScript 语法：shared/service-worker/content/options 全部 PASS
Python compileall：PASS
git diff --check：PASS
```
新增自动化覆盖：

- `queued / downloading / paused / failed / cancelled / completed / prepared / partial / not_in_library` 状态矩阵；
- 12 个并发标签页快速提交同一 RJ，仅 1 次进入核心队列，其余 11 次返回重复任务；
- 桥接停止后重新启动可恢复，200 个 RJ 批量查询成功，201 个请求按上限拒绝；
- 上述测试只使用内存/临时数据库，不接触真实媒体。


完整回归使用仓库外临时目录，未读取或修改真实媒体库。

## 当前站点结构核对

侧边浏览器只读打开了：

```text
https://asmr.one/works
https://asmr.one/work/RJ01651727
```

观察结果：

- 列表存在 `.q-card.fit` 卡片和 `/work/RJ...` 链接，RJ 提取规则匹配；
- Chrome 当前使用 `https://asmr.one/...`，Edge 当前使用 `https://www.asmr.one/...`；扩展现同时声明两个官方域名，避免 Edge 的 `www` 页面漏注入；

补充核对 `/works` 当前两类卡片：

- “All works”主列表的 `.q-card` 内存在独立销量 `span`；RJ01651727 的承载容器为 288 px 宽块级元素，内容脚本会在销量文本之后追加内联控件；
- 顶部“热门作品”轮播卡片当前不显示销量；内容脚本按设计安全回退到卡片信息区，不依赖不存在的销量节点；
- 以上只证明选择器和降级路径匹配当前真实 DOM，Chrome/Edge 安装后的最终视觉位置仍保留为人工验收项。
- 详情标题为 `H1`；
- 详情销量文本为 `销量: 1797`，位于 `.q-pt-sm.q-pb-none` 区域；
- 内容脚本已按该结构优先把标签和按钮放到销量区域；找不到销量时才安全回退到标题/卡片区域。

## Windows 应用界面核对

使用 `C:\tmp\arsm-browser-ext-profile` 隔离 Profile 启动源码版 ARSM Suite：

- 设置页正常打开，无黑屏；
- “浏览器扩展”标题和说明在正常滚动流中可见；
- 真实媒体库未加载；
- 本轮启动的临时 Python/Flet 进程已结束。

## Windows 打包核对

使用仓库外临时虚拟环境执行 `PyInstaller --clean --noconfirm ARSMSuite.spec`：

```text
产物：C:\tmp\arsm-browser-extension-package\dist\ARSM-Suite\ARSM-Suite.exe
EXE 大小：8,385,844 bytes
EXE SHA-256：D3B5C5182C84D595B9EC88C6621B80819E53F6E4C24B9F8974DBEEF334E353F3
源码扩展文件：9
打包扩展文件：9
缺失或哈希不一致：0
额外或哈希不一致：0
```

打包目录中的 `browser_extension/` 与源码逐文件 SHA-256 一致。临时构建产物位于仓库外，未加入 Git。

打包版运行冒烟使用 `C:\tmp\arsm-browser-extension-package-profile` 隔离 Profile：

- 窗口标题 `ARSM Suite 1.0.1`，下载中心正常呈现，无真实资源库；
- 开启桥接后仅监听 `127.0.0.1:17641`；
- 无鉴权健康检查返回 403；
- 固定扩展 ID、Origin 和正确测试令牌的健康检查返回 `ok=true`；
- 点击窗口关闭属于既有“隐藏到托盘”语义，不等同于退出；
- 使用相同 `ARSM_APP_HOME` 执行官方 `ARSM-Suite.exe --shutdown` 返回 0；
- 15 秒内 ARSM/Flet 进程和 17641 监听全部归零。

## 2026-08-20 Chrome / Edge 联调修复

- 用户已在 Chrome 和 Edge 手工加载未打包扩展；
- Chrome 实际扩展 ID 为 `mlncnjadnklkihapfcfcmaoookjlclba`，与桥接固定 ID 一致；
- 首次连接暴露 Chromium MV3 后台请求的 opaque Origin，症状为“浏览器扩展来源未授权”；桥接已只对 `Origin: null` 增加兼容，错误扩展 ID 仍返回 403；
- Edge 实机页面为 `https://www.asmr.one/works?page=10`，旧 manifest 注入控件数为 0；已把 `https://www.asmr.one/*` 加入 content script 范围；
- 断开状态增加 10 秒低频自动重试，ARSM 重启后无需手工反复刷新；活跃下载状态仍按 4 秒刷新；
- 修复后聚焦回归 `20 passed`，完整回归 `408 passed, 3 skipped`；跳过项仍仅为当前 Windows 环境不可创建符号链接。

## 最终人工验收（2026-08-30）

- Edge 列表页和详情页均完成注入、连接和状态显示复核；
- 隔离空库 Profile 使用测试作品 `RJ01276295` 完成一次入队，网页状态回写为“已排队 / 查看下载”；
- 对同一 RJ 的重复请求返回 HTTP 409 `already_queued`，数据库作品数保持 1；
- Edge 多标签显示一致，没有创建第二个作品任务；
- ARSM 完全退出后，页面无需刷新自动切换为“ARSM 未连接 / 设置连接”；同一隔离 Profile 重启后，页面无需刷新自动恢复为“已暂停 / 查看下载”；
- Edge 100% / 125% / 150% 缩放由用户实机确认无重叠、裁切或消失；
- Chrome 稳定版在 `asmr.one` 与 `www.asmr.one` 详情页均显示“已暂停 / 查看下载”；
- Chrome 深色/浅色外观由用户实机确认文字清晰、按钮无重叠或截断；
- 用户从 Chrome 移除 ARSM 扩展后，网页上的两组 ARSM 控件消失；隔离 ARSM 桥接仍返回 HTTP 200，测试库仍为 1 个作品、60 条下载记录；
- 浏览器安全策略要求加载、令牌粘贴和卸载由用户确认或手工完成，验收没有绕过浏览器权限或修改注册表。

说明：隔离 Profile 的音频代理故意指向不可用的 `127.0.0.1:9`，因此测试任务文件下载失败且实际写入 0 字节。这是保护正式媒体的验收配置，不计为产品下载失败；本轮目标是浏览器入队、去重、状态同步和恢复链路。

## 数据保护

```text
真实 E:\arsm 读取：未执行
真实媒体删除：无
真实媒体移动或重命名：无
真实媒体覆盖：无
```
## 2026-08-23 真人用户审计与 Edge 注入证据

- Windows 源码实例在空资源库、隔离 Profile 下完成下载中心、资源库、系统工具、设置和批量粘贴弹窗审计；
- 实机发现批量粘贴弹窗按 Escape 不关闭，已增加应用级 Escape 分发和下载页当前弹窗清理；
- 修复后输入框自动聚焦，按一次 Escape 关闭，队列仍为 0；
- 聚焦回归 `24 passed`；完整回归 `410 passed, 3 skipped`；
- Edge `https://www.asmr.one/works?page=21` 截图和 DOM 均确认 8 组 `ARSM 未连接 / 设置连接` 控件，双域名 manifest 修复生效；
- “设置连接”可打开固定扩展 ID `mlncnjadnklkihapfcfcmaoookjlclba` 的设置页；
- 用户手工保存隔离 Profile 的本机地址与令牌后，列表页 8 组控件的 DOM 状态均切换为 `未入库 / 下载到 ARSM`，桥接鉴权与页面状态同步通过；
- ARSM 设置页新增本机地址和令牌复制按钮，减少手抄错误；令牌仍由用户主动粘贴到扩展设置页，不绕过浏览器安全边界；
- 2026-08-23 当日详情页点击接管曾被浏览器控制通道阻塞；该历史 `NOT RUN` 已在 2026-08-30 最终复核中补齐；
- 2026-08-23 当日 Chrome 未运行；该历史 `NOT RUN` 已在 2026-08-30 最终复核中补齐；
- 详细界面证据与建议见 `docs/ARSM_UX_AUDIT_20260823.md`。

## 2026-08-23 收口状态

- 功能代码检查点：`0fe8afcb0a45f4f554f923b62f68581c7e3ad723`；当前 HEAD 以远端分支最新提交为准；
- 用户确认已推送到 `codex/asmr-browser-extension`；本机因 GitHub 网络中断未独立回读；
- 全量回归：`410 passed, 3 skipped`；扩展打包文件 9/9 哈希一致；
- 仓库内旧 build/dist、日志和缓存已清理，已提交的截图与验收报告保留；
- 新对话从根目录 `HANDOFF.md` 接手。

## 2026-08-30 最终收口

- 当前提交与 GitHub 分支在复核前均为 `86af94ebba776e9c3be12eb2e00eace62891421f`；
- GitHub `main` 为 `b628c86f8217854862716fcdc079f27606a5ecd0`，它是当前分支祖先；分支相对 `main` 为 `0 behind / 19 ahead`；
- GitHub 当前没有该分支的 Actions 运行记录；这表示 CI 尚未运行，不能写成 CI PASS；
- 实机验收发现并修复状态轮询自触发导致的闪烁/限流问题，以及 Chromium MV3 后台请求缺失 Origin 时的最小安全兼容；
- 修复后聚焦回归 `21 passed`、完整回归 `411 passed, 3 skipped`，JavaScript 语法和 `git diff --check` 通过；
- `queue.json` 不存在；隔离运行数据位于仓库外 `C:\tmp`，不得提交；
- 真实 `E:\arsm`、正式数据库和正式下载队列全程零接触；
- 本地验收结论为 `PASS WITH NOTES`，可以建议创建 Draft PR；不得自动合并、Tag 或 Release。
