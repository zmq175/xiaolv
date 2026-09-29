# SPEC-017：采用现成模型调用库

状态：Verified（合成服务与本机端到端，真实供应商待验收）。边界沿用用户已批准的回放入口、费用审计与配置；外部服务使用本机HTTP合成响应。

核对适配库实际行为后采用官方openai Python SDK替换自写Chat Completions/SSE协议，后续按实际供应商扩展。LangGraph、预算账本、参与决策与发送保护保留。

- AC-001：真实模型路径经官方SDK的chat.completions.with_streaming_response.create及parse(AsyncStream[dict])发请求/解码，不再维护另一套SSE解码器；原有沉默/回复闭环经本机HTTP与PG通过。
- AC-002：首内容、空闲和绝对期限包含连接/排队，空心跳不延长；取消关闭流，不发送迟到结果。
- AC-003：关闭自动重试与重定向；单次预留对应单次请求，usage缺失/错误或失败保留未知成本；禁止将缺失usage当0或缓存输入默认全命中。
- AC-004：完成条件为finish_reason=stop、SDK流正常结束且业务结构通过；SDK消费[DONE]而不将其暴露给调用方，不再单独要求观测该标记。拒绝/截断/非法结构不发送，响应和上下文仍有界；保持会话隔离与配置供应商能力要求。
- AC-005：无实际收费调用、无默认外发prompt遥测；迁移差异写入证据，无法被SDK满足的必要产品约束须明确解决，不以通过旧测试为唯一目标。

SDK升级采用公开的原始流解析入口保留token原类型，不能使用会归一化缺失值或自动转换bool/string的统计对象作为费用真值。HTTP响应配额通过公开response hook与字节流包装实现，不解析SSE；请求Accept-Encoding: identity，暂不支持压缩模型响应，以防解压绕过总字节上限。
