# ADR-0003：模型协议交给成熟适配库

状态：Accepted（SPEC-017已实现，本机回归通过；真实供应商兼容待验收）。2026-09-29。

原SPEC-013以httpx直接构建Chat Completions请求并解析SSE。实现动机是首字/空闲/整轮期限、取消、用量不确定性和无自动重试，但这些是应用策略，不构成自建供应商协议栈的理由。用户提出应使用现成模型调用库，决定替换该部分。

保留LangGraph编排，首个标准OpenAI协议适配使用官方openai Python SDK。原拟采用langchain-openai；核对1.6.6源码发现它将缺失usage字段补0，且高层类型归一化不适合费用原值校验。因此此处不额外包一层LangChain模型集成。SDK本身默认对象也会转换bool/string计数；通过公开的chat.completions.with_streaming_response.create和response.parse(to=AsyncStream[dict])读取SDK已经解码的原始事件，自己只校验业务字段，不自建SSE解码器。

其他供应商专有扩展以后使用对应SDK/成熟适配包，不一律改base_url冒充兼容。暂不引入LiteLLM代理或第二套编排框架。

项目仅保留薄适配边界：配置/能力选择、原始回合截止时间与分阶段等待、并发、费用预留结算及审计、结果业务校验。显式关闭库默认自动重试；取消应关闭请求；已有费用未知保留、幂等发送和TTL规则不变。禁止默认打开上传prompt的远程追踪。

迁移先验证现有真实本机HTTP场景，并检查SDK对流结束、拒绝、usage和异常的实际语义。不能用删除失败测试掩盖取消或重复计费回归；若旧测试绑定了自实现协议细节，应明确记录行为调整与对应产品保障。未完成前不声称已经采用SDK。

参考（已阅读）：
- LangChain ChatOpenAI文档：https://docs.langchain.com/oss/python/integrations/chat/openai （支持异步、流式usage、结构化输出、工具调用；第三方专有字段应选供应商适配包）。
- OpenAI Docs SDK说明：https://developers.openai.com/api/docs/libraries （官方Python SDK与编排SDK职责不同）。

实施差异：SDK消费[DONE]标记，公开事件流不单独暴露它；完成采用stop+正常流结束+业务结构校验。无usage依旧未知并保留费用。原测试中stop之后正常EOF但无[DONE]改为允许完整输出，网络截断/非stop/未完成结构仍拒绝。SDK3.20.0使用httpx2，HTTP客户端及测试替身使用同一主版本。
