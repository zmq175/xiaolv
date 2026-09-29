# SPEC-008：原生OneBot WebSocket连接

状态：Verified（本地真实WebSocket服务器）。发送通过已确认DeliveryService边界测试；事件队列是已确认回放入口的原生事件来源。

OneBotWebSocket实现OneBotRPC，显式async上下文管理连接。只使用Authorization Bearer头，不把token放URL；禁用环境代理自动选择，连接/请求/关闭有界。该客户端不自动重发发送动作，不在断连时隐式重新登录。

验收：
- AC-001：本地真实WebSocket服务器收到Bearer头和action/params/唯一echo，正确回执可由DeliveryService确认发送。
- AC-002：交错事件与无关echo不能冒充回执；事件保存在有界队列，由next_event交给入站流程。
- AC-003：并发调用回执乱序仍按echo匹配，不争用多个recv消费者。
- AC-004：服务端断连/丢回执为unknown，不重发；未连接时not_sent；外部取消向上游传播。
- AC-005：事件队列溢出或非法JSON关闭本连接，唤醒等待者，避免无限内存或无期限挂起；关闭后next_event可读已入队事件，耗尽后报连接关闭。

测试服务器仅localhost，合成事件与消息，不连接真实SnowLuma/QQ。真实在线验收仍未完成。

依据：https://websockets.readthedocs.io/en/16.1/reference/asyncio/client.html；SnowLuma源码commit同SPEC-007。
