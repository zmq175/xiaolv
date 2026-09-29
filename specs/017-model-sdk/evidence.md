# 验证记录

2026-09-29。官方openai Python SDK 3.20.0，httpx2 2.13.1，uv.lock已锁定。所有模型请求为合成本机服务/HTTP替身，不调用收费模型。

## 选型与红绿

先核对langchain-openai 1.6.6的_create_usage_metadata实现：缺失prompt/completion会补0，缺失total会合成总数。原拟方案因此调整为直接使用官方SDK，LangGraph编排保留，未使用的langchain-openai和tokenizer依赖已移除。

- 标准SSE单CR换行测试在旧解码器返回model_error→官方SDK请求/解码后通过，并观察SDK客户端标识请求头。
- 原有超大未终止行测试在初次SDK替换后错误通过silence→HTTP公开response hook与字节流限额后恢复拒绝并及时关闭。包装只计HTTP字节，不解析SSE；压缩响应在读取body前拒绝（请求identity编码）。
- SDK默认ChatCompletionChunk会将bool/string计数转成整数，原有两项usage未知测试失败→改用SDK公开with_streaming_response.create及parse(to=AsyncStream[dict])后通过。没有覆写SDK私有方法，费用校验保留原值。
- SDK3默认HTTP客户端类型为httpx2；静态检查抓到旧httpx类型不匹配→产品客户端及3个测试替身统一版本后通过。
- 首次单CR测试在默认受限沙箱报告失败且清理持续等待；检查对应活进程后中断，确认退出，再在本机测试权限下启用faulthandler复验，0.57秒通过。没有把该次受限执行算作通过；后续完整回归在同一可运行环境完成。未断言已确定沙箱内等待的底层根因。

## 明确的行为调整

旧实现要求自己看到[DONE]；SDK负责消费此标记，公开迭代不返回它。现完成条件为收到finish_reason=stop、流正常结束、业务结构通过。旧参数化的stop+正常EOF但无[DONE]预期拒绝，替换为独立回归：允许完成，同时缺失usage继续报告None，绝不记零费用。缺stop、length、tool_calls、refusal、网络失败及超时拒绝仍保留。该新测试首次即通过，是迁移语义回归，不冒称新的红绿。

补充部分usage字段缺失的两项回归，均保持未知。压缩响应拒绝测试首次通过，验证字节上限适用边界，不表示支持所有服务商的传输方式。

## 检查与AC映射

- 模型边界阶段：53项通过，包含原有首内容/空闲/总期限、取消关闭、HTTP 302/401/429/503不跳转/不重试、会话隔离、格式/长度、usage及新CR帧；追加两个部分usage和一个压缩测试进入完整套件。
- `uv run ruff check .`通过；`uv run ruff format --check .`通过；`uv run mypy src`35个源文件通过。
- 设置本机PG隔离DSN执行 `uv run pytest -q --tb=short`：**310 passed in 44.24s，无跳过**。覆盖持久预算、并发预留、SIGKILL费用保留、在线CLI原生发送及trace关联。

AC-001 → streamed_model_reply/carriage_return及test_live在线闭环；AC-002 → first_content/heartbeats/pause/continuous_slow/cancelling/waiting_for_shared_slot；AC-003 → HTTP错误参数化、usage参数化及test_model_budget；AC-004 → incomplete_or_nontext_finish/clean_end/oversized/compressed/invalid_participation/cross_conversation；AC-005 →源码路径、依赖锁定、本证据和现有合成服务测试。

## 未验收

真实供应商结构化输出/usage、认证、稳定性、自然度及费用未测；不宣称任意“兼容”端点都支持此配置。当前要求identity响应编码；其他提供商/多模态通过后续适配实现。SDK上传/追踪没有开启，日志为本机标准logging。腾讯文档尚未同步本增量；GitHub CI另行报告，不用本机结果冒充。
