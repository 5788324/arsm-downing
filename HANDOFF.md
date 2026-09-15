# ARSM Suite 最终验收交接

> 更新日期：2026-08-30
> 仓库：`5788324/arsm-downing`
> 唯一工作区：`G:\Codex\ARSM Suite\ARSM Suite`
> 分支：`codex/asmr-browser-extension`
> 功能代码检查点：`0fe8afcb0a45f4f554f923b62f68581c7e3ad723`
> 最终验收前 HEAD / GitHub 分支：`86af94ebba776e9c3be12eb2e00eace62891421f`
> GitHub `main`：`b628c86f8217854862716fcdc079f27606a5ecd0`
> 结论：`PASS WITH NOTES / DRAFT PR READY`

## 一、最终完成内容

1. Manifest V3 扩展支持 `asmr.one` 与 `www.asmr.one`。
2. 列表和详情页显示入库/队列/连接状态，并将 RJ 交给 ARSM 核心下载器。
3. loopback 桥接具备固定扩展 ID、48 位令牌、限流、请求大小限制和重复保护。
4. 设置页提供安装管理、连接检查、地址/令牌复制、令牌重建和卸载引导。
5. 修复 Windows 批量粘贴弹窗 Escape 行为。
6. 最终实机发现并修复两项浏览器链路问题：
   - 扩展自身 DOM 更新触发 MutationObserver 循环，最终命中限流并造成状态闪烁；
   - Chromium MV3 后台请求缺失 Origin 时，需要在 loopback、固定扩展 ID 和强令牌同时有效时安全放行。
7. 上述修复均增加自动化测试。

## 二、最终证据

自动门禁：

```text
聚焦回归：21 passed
完整回归：411 passed, 3 skipped
JavaScript 语法：PASS
git diff --check：PASS
```

实机：

- Edge 列表页、详情页、连接和状态显示通过；
- 隔离空库测试 `RJ01276295` 一次入队成功，重复请求返回 HTTP 409 `already_queued`；
- 多标签没有产生第二个作品任务；
- ARSM 完全退出后页面无需刷新自动断开；重启后无需刷新自动恢复；
- Edge 100% / 125% / 150% 缩放正常；
- Chrome `asmr.one` / `www.asmr.one` 双域名详情页均显示“已暂停 / 查看下载”；
- Chrome 深色/浅色外观正常；
- Chrome 移除 ARSM 扩展后网页控件消失，隔离 ARSM 桥接仍返回 HTTP 200；
- 隔离数据库保持 1 个作品 / 60 条下载记录；
- `queue.json` 不存在。

数据边界：

- 隔离 Profile：`C:\tmp\arsm-browser-extension-flicker-retest-profile`；
- 下载代理故意设为不可用的 `127.0.0.1:9`，实际媒体写入 0 字节；
- 真实 `E:\arsm`、正式数据库、正式队列全程零接触；
- 不提交测试 Profile、数据库、日志、缓存、临时媒体、build 或 dist。

## 三、GitHub 核对

- 本地 HEAD 与 GitHub 分支在最终文档写入前均为 `86af94e`；
- GitHub `main@b628c86` 是当前分支祖先；
- 分支相对 `main`：`0 behind / 19 ahead`；
- 当前分支没有 GitHub Actions 运行记录，不能写成 CI PASS；
- 本轮只允许普通 fast-forward push，禁止强推、reset、rebase 或自动合并。

## 四、当前未提交修改

源码与测试：

- `browser_extension/content.js`；
- `core/browser_bridge.py`；
- `tests/test_browser_bridge.py`；
- `tests/test_browser_extension_contract.py`。

最终状态文档：

- `HANDOFF.md`；
- `CURRENT_STATE.md`；
- `NEXT_TASK_ROADMAP.md`；
- `docs/BROWSER_EXTENSION_TASKS.md`；
- `docs/BROWSER_EXTENSION_ACCEPTANCE.md`；
- `docs/ARSM_UX_AUDIT_20260823.md`。

## 五、剩余动作

1. 复核最终 diff，确认没有运行产物或正式数据路径变更。
2. 将上述源码、测试和文档形成一个最终验收提交。
3. 普通 fast-forward push 到 `codex/asmr-browser-extension`，禁止强推。
4. 建议用户创建 Draft PR；PR CI 全绿并完成审查前不得转 Ready。
5. 不自动合并、Tag 或 Release。

## 六、安全边界

- 不读取、写入、删除、移动、覆盖或重命名 `E:\arsm` 中的媒体；
- 不接触正式数据库和正式下载队列；
- 不把无 CI 运行记录写成 CI PASS；
- 不把故意阻断的隔离下载写成真实下载成功或产品失败；
- 发现新缺陷时先复现、补测试，再做最小修复。
