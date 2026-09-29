# SPEC-013 验证证据

2026-09-29，38个模型入口/配置用例，全量组合209 passed（无skip）。

红绿链：模型未实现→完整SSE经TextRuntime发送1通过；有效JSON但length/tool_calls/content_filter/缺少stop/DONE仍被发送的5种失败→全部拒绝；首token阶段未计等待headers→超时关闭；并发未限制导致排队回合仍调用HTTP→共享名额及期限；超大未结束SSE行继续读取→按累计解码字节上限立即关闭；5万字目标无界外发→明确截断并限制近期窗口；10种无效配置未拒绝→构造前拒绝；refusal/tool意图被当纯文本3失败→拒绝；跨会话上下文外发失败→HTTP调用前拒绝。

补充回归覆盖silence单次请求、空心跳/空delta、流内容停顿、持续慢流总期限、取消关闭、HTTP 302/401/429/503不重试、不跟随跳转、非法参与schema。本机asyncio TCP服务器接收真正HTTP请求并分段写出SSE，确认真实网络路径一次发送完整回复；未连接真实模型供应商。

实际命令：`UV_CACHE_DIR=/tmp/xiaolv-uv-cache uv run --offline --locked pytest tests/test_chat_model.py -q --tb=short`（38例包含本机TCP，需要环境允许localhost socket）。全量`pytest -q --tb=short`配置专用PG测试库；另执行ruff check、ruff format --check、mypy src（27个源文件）。HTTPX由已有间接依赖0.28.1转为直接声明，uv离线解析锁定。

AC映射：001首个模型回复/本机HTTP/跨会话拒绝；002沉默/非法schema/非stop/工具意图；003初始headers/心跳/停顿/持续慢流/取消；004共享并发/HTTP错误无重试；005输入与响应边界已验证，用量缺失和usage保存尚未实现；00610类配置拒绝。状态保持Implementing，下一步完成用量结果及计费衔接，不能把缺失usage当作0费用。

限制：当前初值每请求max_completion_tokens=512、上下文总12000字符、目标与单条消息最多1000字符（带截断标记）、最多30条；实际token数与字符数不同，仍需成本预留。默认首内容12秒/内容停顿8秒、并发2，需真实供应商校准。参与与生成各一个请求，尚无DEFER/工具循环/媒介选择，也未通过在线启动命令连接QQ。

协议来源：[Chat Completions请求与SSE例子](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)、[结构化输出](https://developers.openai.com/api/docs/guides/structured-outputs)。2026-09-29通过OpenAI Docs及官方网页核对；文档接口的reference markdown返回404后已读取官方HTML。这里只采用兼容协议，不选定收费供应商。

补齐usage与超时验证：标准最终usage返回80输入/5输出/85总token/32缓存，UsageSink只接收无内容的调用事实。缺失、错误类型、负数、合计冲突、缓存越界均为None；仅中途usage不作为最终账单。失败与取消有对应未知用量记录；排队未获取名额时过期不产生已调用记录；sink异常阻止继续生成/发送。真实HTTP延迟5.15秒、配置首内容7秒的测试先被HTTPX默认5秒提前中止，关闭重复超时机制后通过，仍受应用阶段与绝对deadline约束。

新增13例使模型套件达到51例，全量222 passed（无skip，13.62秒）；ruff、format检查及mypy 28个源文件通过。AC-005的未来计费接口已由ModelCallReport/TokenUsage和异步UsageSink落实；前文“usage保存尚未实现”指此前状态，本切片现已完成回调审计，持久化、调用前预留和费用结算仍由下一规格实现。未将内存测试sink冒充生产持久账本。

后续实施变更：SPEC-017使用官方SDK替换手写SSE，完成语义更新为stop+正常流结束+业务结构通过，不单独要求DONE。上述红绿为当时历史证据，当前差异及310项回归见017/evidence.md。
