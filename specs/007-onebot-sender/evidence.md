# SPEC-007证据

2026-09-29，通过DeliveryService观察外部OneBotRPC请求。群聊未实现unknown→1passed；私聊误用群聊action→2passed；未注册会话unknown→3passed；5类缺失/非法回执误判confirmed→8passed；明确协议拒绝unknown→10passed；3类非法本地目标误发→13passed。

标准库协议适配不调用MCP。SnowLuma本地源码契约已核对，但RPC替身通过不能视为WebSocket连接或真实QQ发送通过；真实@、入站与媒体另行实现。
