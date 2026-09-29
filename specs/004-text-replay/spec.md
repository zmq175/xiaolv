# SPEC-004：LangGraph文字回放闭环

状态：Verified（本地假模型回放）。2026-09-29用户确认回放入口、DeliveryService边界，内部细节自主决定。

## 接口与范围

`TextRuntime.run(candidate) -> str终态`。候选包含conversation_id、event_id、text、expires_at及generation_epoch；候选已由上游选为可评估回合，不代表每条群消息必须回复。注入ConversationModel（decide返回respond/silence，reply返回文字）、DeliveryService和时钟。LangGraph只做参与与生成，平台发送在图外。

## 验收条件

- AC-001：模型决定silence时不生成回复、不发送，返回silence。
- AC-002：模型决定respond时将生成文字交给原生DeliveryService，返回其结果。
- AC-003：入口已过期不调用模型；生成结束过期不发送，截止时间不刷新。
- AC-004：整图等待受剩余TTL限制；永不返回的模型被取消，返回expired，不能占住回放任务。
- AC-005：文字空白或超过配置长度拒绝发送，返回invalid_reply；不机械截断。
- AC-006：同会话同事件ID重放使用相同outgoing_id，不重复发送；不同会话相同event_id不冲突。
- AC-007：模型异常返回model_error，不向群发堆栈；取消由调用者传播；无效决策不能隐式当respond。

- AC-008：`python -m xiaolv.replay`提供纯本地假模型演示，输出一轮沉默、一轮确认发送及发送内容；不连接QQ或收费API。

## 限制

只支持单条文字、可控假模型和回放平台；不含原始入站持久化、合并调度、真实LLM、权限、配额、人物记忆或工具循环。不宣称P1完整交付。epoch由上游提供，发送出口再核对，不将所有新消息视为旧回复失效。

## 技术依据

LangGraph StateGraph编译后使用ainvoke运行；版本以uv.lock为准。
https://reference.langchain.com/python/langgraph/graph/state/StateGraph
