# SPEC-009：真正的QQ成员@

状态：Verified（协议与持久化）。沿用DeliveryService已确认边界。

DeliveryRequest新增mentions元组，内容是内部成员账号引用，不是模型任意拼接的QQ号码。OneBotSender从可信、按会话隔离的member_accounts映射解析为QQ账号，生成at段；普通文本@保持text段。

验收：
- AC-001：群聊已登记成员输出at段data.qq为字符串QQ账号，后接原文text段。
- AC-002：未登记成员、跨会话成员、all、私聊中的mention拒绝为not_sent，不调用平台；重复成员引用仅生成一次at。
- AC-003：outbox持久化mentions；重建service后同请求不重发，修改mentions视为payload冲突。

可信映射是适配器输入契约；当前验证不包含自动群成员同步、真实QQ通知、同名消歧或退群刷新。这些会在入站/人物模块补齐。@全体尚未实现授权，始终拒绝。Alembic增量迁移给旧记录填空数组。
