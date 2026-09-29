# ADR-0003：模型协议交给成熟适配库

状态：Accepted（待实现与兼容验证）。2026-09-29。

当前SPEC-013以httpx直接构建Chat Completions请求并解析SSE。实现动机是首字/空闲/整轮期限、取消、用量不确定性和无自动重试，但这些是应用策略，不构成自建供应商协议栈的理由。用户提出应使用现成模型调用库，决定替换该部分。

保留LangGraph编排，模型接入采用LangChain维护的供应商集成。首个标准OpenAI协议适配使用langchain-openai的ChatOpenAI，底层使用官方OpenAI SDK；供应商专有扩展使用相应官方/成熟适配包，不一律改base_url冒充兼容。结构化输出、工具消息和流事件优先使用库接口。暂不额外引入LiteLLM代理或第二套编排框架。

项目仅保留薄适配边界：配置/能力选择、原始回合截止时间与分阶段等待、并发、费用预留结算及审计、结果业务校验。显式关闭库默认自动重试；取消应关闭请求；已有费用未知保留、幂等发送和TTL规则不变。禁止默认打开上传prompt的远程追踪。

迁移先验证现有真实本机HTTP场景，并检查SDK对流结束、拒绝、usage和异常的实际语义。不能用删除失败测试掩盖取消或重复计费回归；若旧测试绑定了自实现协议细节，应明确记录行为调整与对应产品保障。未完成前不声称已经采用SDK。

参考（已阅读）：
- LangChain ChatOpenAI文档：https://docs.langchain.com/oss/python/integrations/chat/openai （支持异步、流式usage、结构化输出、工具调用；第三方专有字段应选供应商适配包）。
- OpenAI Docs SDK说明：https://developers.openai.com/api/docs/libraries （官方Python SDK与编排SDK职责不同）。
