# SPEC-008证据

2026-09-29，websockets 16.1.1，固定于uv.lock。所有连接均为临时localhost服务器，无QQ登录或发送。

命令：`uv run --offline --locked pytest tests/test_onebot_websocket.py -q --tb=short`。

- 认证发送：NotImplementedError→1 passed。
- 事件与回执混流：unknown而非confirmed→2 passed。
- 并发乱序：第二调用争用recv导致unknown→单接收协程按echo分发，3 passed。
- 断连不重发、未连接not_sent：已有逻辑直接回归通过，5 passed。
- 事件消费者断连唤醒：外层保险超时→6 passed。
- 非法JSON生命周期：退出上下文时异常泄漏→7 passed。
- 129个事件超过128队列：QueueFull泄漏→8 passed，保留已入队128条。
- 非对象JSON：list/null/int触发AttributeError→11 passed。
- 取消后迟到回执和下一请求、丢回执超时：已有逻辑直接回归通过，13 passed。

无自动重连/发送重试。原生连接测试通过不等于真实SnowLuma会话兼容验收；原始事件尚未归一化/持久化到Inbox。入站过载会断连，重连后缺失消息恢复策略仍待完成。
