# SPEC-011：持久入站与会话上下文

状态：Verified（仅本规格范围）。使用已确认回放入口边界，真实PG验证。

IncomingMessages.receive(frame)先经OneBotIngress归一化，再通过InboxStore原子登记；返回stored/duplicate/ignored及事件。recent(conversation_id, limit)返回该会话按发生时间排序的最近事件，给内部上下文构建使用，不作为模型可任意指定会话的工具。

context(conversation_id, limit)返回同一数据库快照的revision和messages；不存在的会话返回版本0和空消息。recent是只取messages的便捷入口。

验收：

- AC-001：消息存储后重建入口/数据库连接仍可读取，包含结构化parts、身份及原始时刻。
- AC-002：同conversation_id+message_id只登记一次，重复推送不得刷新内容、接收时间或TTL依据。
- AC-003：不同会话相同message_id独立存储；recent不混入其他群/私聊。
- AC-004：并发重复入站只有一次stored；revision与message在一个事务提交，不因原始消息入站增加epoch。
- AC-005：自己的消息/非消息事件返回ignored，不存储；历史事件可存储但保留is_historical，不能自动触发实时回复。
- AC-006：recent有界（1–200），按发生时间、入站序号稳定排序；数据库故障不能返回伪成功。

迁移0003建立app.messages并扩展conversation_state.revision。此切片不自动调用模型、授权发送或取消旧回合，调度按后续规格实现。
