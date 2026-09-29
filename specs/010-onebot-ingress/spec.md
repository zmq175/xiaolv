# SPEC-010：OneBot入站消息归一化

状态：Verified（仅本规格范围）。沿用已确认回放入口测试边界。

`OneBotIngress.receive(frame, received_at) -> ChatEvent | None`是原生事件入口的纯转换部分，不调用模型、不发送消息。输入是已认证OneBot连接提供的JSON对象；归一化对象不依赖QQ SDK。

验收：
- AC-001：群聊会话键包含平台、bot账号、类型、群号；人物账号仅按平台稳定账号标识，昵称不是身份主键。
- AC-002：私聊与群临时会话分别隔离，临时会话包含来源群；相同群友在不同会话中仍为同一人物账号。
- AC-003：meta/notice/request/message_sent和自己的message不触发聊天，返回None；其他bot账号事件拒绝。
- AC-004：text只拼接text段；at、reply、image、face、record保持结构化，不把CQ字符串解析为动作；不在接收时调用视觉/语音模型。
- AC-005：无效ID、无时区received_at、非法时间、非数组message和畸形段以IngressError拒绝，不包含原始消息内容。
- AC-006：保留发生与接收时间；超过队列年龄的历史消息标is_historical，未来时间标clock_skew并钳制effective_time到received_at，不允许延长未来TTL。

媒体只保存引用，尚未获取/理解。这里不做群消息合并、人物推断或数据库入站去重，不把每条归一化消息直接变成新聊天回合。

依据：SnowLuma commit 1ef9a2c33023b5fcb400865c8281d2dfd190540b，event-converter/to-message.ts及envelope.ts；临时会话来源群为sender.group_id。
