# 验证证据

2026-09-29，沿用在线入口/回放/DeliveryService 边界。本地真实 PG 与合成模型 HTTP、OneBot WebSocket；未访问真实 QQ 或付费模型。

- 首个在线模型引用测试先 Red：旧模型不接受引用输出，等待发送结果超过 5 秒。增加引用 schema、可见候选解析、TextReply.reply_to、运行时唯一性检查、动态 get_msg 核实、原生 reply 及读回后，与文字/@回归一起 Green：3 passed。
- 在线引用、引用加@、平台静默丢段、未知 message_ref、直接平台 ID 共 5 例通过；后四项为已有实现的回归，未虚称 Red。
- 发送边界新增 11 例：群/好友引用及重复抑制，读回缺失/错误目标/跨群/非法 ID/查询 NotSent 异常仍为 unknown且不重发；目标跨群、好友不匹配、临时会话不能作为好友引用。与既有 OneBot 用例共 57 passed。
- 模型选择已知重复消息 ID 被拒绝，引用上下文/选择定向 6 passed。
- 全量 375 passed in 52.20s，无跳过；ruff check、format（164 文件）、mypy（36 源码文件）与 git diff --check 通过。

动态在线准备启用 verify_quotes；静态 OneBotSender 的旧可信映射协议用例保持默认仅核对发送回执，不能用那些旧用例声称读回完成。在线引用意图仍持久化到既有 outbox.reply_to；原有跨重启幂等与 payload 冲突测试继续适用。

SnowLuma 的 get_msg 读取缓存。前置核实证明当前会话中的目标存在，不证明序号仍可用；后置核实检查平台缓存的转换后引用段。即使两者成功，也不保证 QQ 客户端显示正确。若后台缓存尚未建立，保守返回 unknown，不自动重试发送或另发正文。

前序 eb14188 CI 36573041654 已确认 success，不作为本提交 CI 证据。真实好友/群聊显示、撤回竞态与供应商结构化输出支持仍待账户验收。
