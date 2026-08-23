# ARSM Suite 新对话交接

> 交接日期：2026-08-23
> 仓库：`5788324/arsm-downing`
> 工作区：`G:\Codex\Yang Kura\arsm-v101-fix-audit`
> 分支：`codex/asmr-browser-extension`
> 功能代码检查点：`0fe8afcb0a45f4f554f923b62f68581c7e3ad723`；当前 HEAD 以远端分支最新提交为准，其后仅允许存在交接文档提交
> 推送：用户确认已完成；当前工作区无法因网络原因独立回读 GitHub

## 一、这轮完成了什么

1. 完成 Manifest V3 浏览器扩展，支持 `asmr.one` 与 `www.asmr.one`。
2. 海报列表显示“已入库 / 未入库 / ARSM 未连接”等状态；未入库作品提供“下载到 ARSM”。
3. 详情页实现“使用 ARSM 下载”入口；扩展只提交 RJ，实际下载仍由 ARSM 核心负责。
4. 完成本机 loopback 桥接：固定扩展 ID、48 位令牌、限流、批量状态、入队和任务状态接口。
5. 兼容 Chromium MV3 的 opaque Origin，同时继续强制校验扩展 ID 和令牌。
6. 断开时每 10 秒恢复轮询，活动任务每 4 秒刷新。
7. 设置页提供启停、连接检查、打开扩展目录、地址/令牌复制、令牌重建和卸载引导。
8. Windows 真人 UI 审计发现并修复批量粘贴弹窗 Escape 不关闭。
9. 更新任务、验收、路线图和审计报告，保存 7 张 Git 跟踪的 UI 证据截图。

## 二、已验证事实

```text
完整 pytest：410 passed, 3 skipped
跳过原因：Windows 环境无法创建 symbolic link
Python compileall：PASS
扩展 JS node --check：4/4 PASS
git diff --check：PASS
扩展源码与隔离打包文件：9/9 SHA-256 一致
工作区提交后：clean
真实 E:\arsm：未访问、未修改
```

Windows 可见验证：

- 下载中心、资源库、系统工具、设置页无黑屏、异常横向滚动或关键按钮裁切；
- 批量输入自动聚焦，Escape 一次关闭，队列保持 0；
- 地址和令牌复制按钮可用；
- Edge 列表页注入 8 组控件；保存隔离 Profile 令牌后均显示“未入库 / 下载到 ARSM”；
- ARSM 正常关闭后本轮进程和 `127.0.0.1:17641` 监听归零。

## 三、不得提前写成 PASS 的项目

- Edge 详情页按钮的最终视觉和点击；
- 隔离空库测试 RJ 入队、重复入队保护、任务状态回写；
- ARSM 退出后扩展断开、重启后无需刷新自动恢复；
- Chrome 当前稳定版；
- Chrome/Edge 多标签、100%/125%/150% 缩放、深浅外观和卸载矩阵。

浏览器控制阻塞：Codex Browser 的 Edge 扩展已安装并启用，但原生通信注册项缺失，标签可以枚举但接管超时。后续从 Codex 插件界面重装 Browser 插件；不要自行修改注册表。

## 四、后续任务顺序

1. 先运行 `git status --short --branch` 和 `git rev-parse HEAD`，必须保持上述分支、SHA 和 clean。
2. 网络正常后只读核对 GitHub 分支 SHA、远端 CI、当前 `main` 以及分支相对 main 的 diff；本地 `origin` 指向一个本地仓库路径，核对 GitHub 时应使用明确的 GitHub URL。
3. 重装/修复 Codex Browser 插件后，用 Edge 补齐详情页、空库入队、重复保护、退出/重启恢复。
4. 启动 Chrome 后执行同一最小矩阵。
5. 补多标签、缩放、深浅外观和卸载验证，只更新文档和测试证据；若无真实缺陷，不改业务代码。
6. 验收完成后再决定是否创建 Draft PR。禁止自动合并、Tag、Release 或写入真实媒体库。

## 五、数据与 Git 边界

- 不删除、移动、覆盖或重命名 `E:\arsm` 中的任何媒体。
- 浏览器入队只使用隔离空库 Profile 和测试 RJ。
- 不提交 build、dist、日志、缓存、测试 Profile 或临时媒体。
- 不把 NOT RUN、网络失败或浏览器控制失败写成产品 PASS/FAIL。
- 发现 Minor 只记录；只有可复现真实缺陷才修改代码并补测试。

## 六、关键文件

- `CURRENT_STATE.md`：当前事实源；
- `NEXT_TASK_ROADMAP.md`：后续任务顺序；
- `docs/BROWSER_EXTENSION_TASKS.md`：功能矩阵；
- `docs/BROWSER_EXTENSION_ACCEPTANCE.md`：自动化和实机证据；
- `docs/ARSM_UX_AUDIT_20260823.md`：真人 UI 审计与截图；
- `WORKLOG.md`：历史工作记录。

## 七、给新对话的提示词

```text
请接手 ARSM Suite 浏览器扩展分支的最终验收收口。

工作区：G:\Codex\Yang Kura\arsm-v101-fix-audit
仓库：5788324/arsm-downing
分支：codex/asmr-browser-extension
功能代码检查点：0fe8afcb0a45f4f554f923b62f68581c7e3ad723（当前 HEAD 以远端分支最新提交为准，并确认它包含此检查点）

先完整阅读：
1. HANDOFF.md
2. CURRENT_STATE.md
3. NEXT_TASK_ROADMAP.md
4. docs/BROWSER_EXTENSION_TASKS.md
5. docs/BROWSER_EXTENSION_ACCEPTANCE.md
6. docs/ARSM_UX_AUDIT_20260823.md

先只读核对 git status、HEAD、GitHub 远端分支、CI、main 和分支 diff。不得 reset、rebase、强推或自动合并。

已完成：浏览器扩展、本机安全桥接、双域名注入、设置页管理和复制按钮、断线恢复、Escape 弹窗修复；本地完整回归 410 passed / 3 skipped；Edge 列表页连接状态通过；真实 E:\arsm 零接触。

待完成：
- 修复 Codex Browser 控制通道（优先从 Codex 插件界面重装 Browser 插件，不改注册表）；
- Edge 详情页按钮、隔离空库测试 RJ 入队、重复保护、ARSM 退出/重启自动恢复；
- Chrome 最小矩阵；
- 多标签、100%/125%/150% 缩放、深浅外观和卸载；
- 更新验收文档；全部通过后再建议 Draft PR，不自动合并、Tag 或 Release。

安全边界：不读写真实 E:\arsm，不接触正式数据库/下载队列，不提交截图以外的新运行产物，不把 NOT RUN 写成 PASS。发现真实缺陷时先复现、补测试、做最小修复。
```