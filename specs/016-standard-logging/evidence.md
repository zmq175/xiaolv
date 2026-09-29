# 验证记录

2026-09-29，标准logging + OpenTelemetry API/SDK 1.45.0（依赖已锁定）。没有配置远程exporter或Collector。

## 红绿

- 标准Logger输出：缺少logging_setup模块失败→标准StreamHandler与自定义LineFormatter后通过，实际文件/行、INFO、+0800毫秒、__msg和业务字段可由原codec解析。
- 并发OpenTelemetry上下文：原先两个任务均为零trace失败→Formatter读取活动span后，通过不同trace且匹配各自SDK上下文的验证。
- 异常：缺exception_type失败→只提取异常类型与无源码/局部变量的栈位置后通过；异常正文不在输出里。
- 标准文件轮转：缺filename参数失败→使用RotatingFileHandler后最多两个测试备份，所有行可解析，最后一条在当前文件。
- 日志配置：未知log_*环境字段失败→公开Settings校验与配置后通过。
- CLI：stderr没有生命周期日志失败→logging配置与OpenTelemetry初始化后通过。初次修复发现__main__命名空间不在xiaolv下，改用明确的xiaolv.lifecycle后通过。
- 在线CLI组合：原先只有生命周期日志失败→入站、参与、用量、发送与回合接线后通过；初次用量sink未成功接线，保持失败直到补上。随后模型两次调用共用同一span失败→使用OpenTelemetry官方异步装饰器后通过，两个不同span属于同一回合trace。
- 重复配置/级别过滤及非法级别/轮转限额为已有框架行为和校验的回归检查，首次通过；不冒称新增红绿。

AC-001 → test_standard_logger；AC-002 → test_standard_file_rotation/reconfiguration；AC-003 → test_otel_trace_context/exception_logs；AC-004 → test_cli及test_live的live_command；AC-005 → test_settings的logging_output/invalid_log_settings及docs/logging.md。

## 实际检查

`uv run ruff check .`通过；`uv run ruff format --check .`通过；`uv run mypy src`35个源文件通过。

设置本机隔离PG测试DSN执行 `uv run pytest -q --tb=short`：**306 passed in 37.64s，无跳过**。包含原有模型截止/费用保留/恢复测试与真实子进程；所有平台和模型是合成本机服务，没有真实QQ或付费调用。

## 限制

日志框架接线完成，不代表完整可观测性完成：跨数据库队列来源trace传播、OTLP、指标/告警、磁盘故障/生产留存验证仍待后续。默认20MiB×最多6文件为大小轮转，不伪称按7天保留。日志业务字段必须由开发者控制，Formatter不能自动发现任意字符串中的秘密。未知第三方日志不自动纳入应用文件。腾讯文档尚未同步。
