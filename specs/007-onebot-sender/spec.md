# SPEC-007：原生OneBot文字发送

状态：Verified（外部RPC替身）。使用已确认DeliveryService公开测试边界，观察外部OneBot请求及发送结果。

## 接口与范围

OneBotSender实现PlatformSender，通过原生OneBotRPC调用send_group_msg或send_private_msg。routes由可信应用配置/入站适配器提供，内部conversation_id映射到固定QQ目标；模型不能改写group_id。消息始终使用数组段，文本中的CQ码按纯文本发送。

## 验收

- AC-001：群聊发送真实text段，正确映射固定group_id；成功必须status=ok、retcode为整数0且有合法message_id。
- AC-002：私聊走send_private_msg与user_id，不误投群聊。
- AC-003：未登记会话、本地非法目标拒绝，DeliveryService结果not_sent，RPC不被调用。
- AC-004：字段缺失、异常回执或通用远端失败保持unknown；明确参数错误1400/未知动作1404返回not_sent，不自动重试。
- AC-005：纯文本@和CQ语法不会变为通知/图片等消息段。

本切片先验证原生请求和回执契约，WebSocket连接、事件入口、真正@段及媒体在后续增量实现。没有使用MCP。测试合成QQ号码，不运行真实群发送。

## 源码依据

SnowLuma本地commit 1ef9a2c33023b5fcb400865c8281d2dfd190540b：packages/onebot/src/actions/message.ts、types.ts、network/utils.ts。成功send_group_msg/send_private_msg返回data.message_id；Bearer认证在后续传输层实现。
