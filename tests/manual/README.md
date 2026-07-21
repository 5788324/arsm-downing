# Manual 测试

该目录用于必须由人工明确启动或观察的测试，测试文件必须标记
`@pytest.mark.manual`。默认 `python -m pytest` 不会执行它们。

真实 ASMR.one 下载、API/代理诊断、需要 RJ 参数的脚本和有副作用的文件实验，
迁移后应放在这里。
