# T10 批量粘贴修复

## 背景

Windows 隔离验收中，Flet 0.27.6 原生 FilePicker 即使注册到 `page.overlay`，最终 EXE 仍未可靠弹出选档框。该问题阻塞批量预览取消/确认的现场证据。

## 决策

RC2 主入口不再依赖 FilePicker。下载页按钮改为“批量粘贴”，直接打开应用内多行 TextField。

## 交互

```text
批量粘贴
→ 多行输入 RJ / 数字 / ASMR.one URL
→ 预览
→ 显示 ready、无效、输入重复、当前活动、队列已有、资源库已有、历史完成、待复核
→ 取消或确认
```

## 副作用边界

- 输入对话框取消：零副作用；
- 预览阶段：只读 SQLite 和配置根目录的顶层 RJ 前缀，不写数据库、不建目录、不请求网络；
- 预览取消：零副作用；
- 确认：只对 `ready` 项调用现有 `start_download`；
- 其他分类永不提交。

## 自动测试

新增覆盖：

1. 主按钮为“批量粘贴”，FilePicker 不在 page.overlay；
2. 点击后打开 multiline TextField；
3. 输入对话框取消后 DB/目录/调用清单不变；
4. 预览取消后 DB/目录/调用清单不变；
5. 最终确认只提交 ready；
6. 重开对话框不保留旧输入。

当前 Linux 容器使用不进入交付包的临时 Flet 接口桩：238/238 PASS。真实 Flet 0.27.6 最终 GUI 仍由 Codex验收。

## Windows 放行条件

- 最终 EXE 可打开批量粘贴对话框；
- 混合输入分类数量正确；
- 取消前后 works/downloads/队列/目录零变化；
- 确认后新增任务数等于 ready 数；
- 重新执行全量测试、构建和 SHA-256；
- 通过后才允许一个 commit、一次 push 和一个新 PR。
