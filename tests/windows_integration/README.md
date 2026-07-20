# Windows Integration 测试

该目录用于依赖 Windows 桌面、Flet runtime、Windows 文件锁、长路径或复制资源库
沙盒的测试，必须标记 `@pytest.mark.windows_integration`。

默认 portable gate 不会执行这些测试。它们只交给 Codex，并且不得面向活跃正式
数据库或正式媒体库运行。
