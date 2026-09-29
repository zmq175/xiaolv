# 验证证据

2026-09-29，测试通过 DeliveryService 注入 OneBotPreparation，观察原生 RPC 外部边界，不测试内部辅助方法。

1. 动态成员原生 @：先因不存在 OneBotPreparation 导致 Red，增加读取与映射后 Green。
2. 不可信/不存在成员的 6 个响应：失败状态、布尔 retcode、跨群数据先有 3 例 Red（误进入发送，得到 unknown），字符串账号、损坏成员、空表首先已拒绝。完善严格校验后 6 例 Green。
3. 私聊 mention、all、昵称、非规范账号、尚未解析的引用：5 例先发现多余查询，前置拒绝后 Green。
4. 普通文字：先被错误送入成员查询而 not_sent；加入无 mention 快速路径后 Green。
5. 查询返回后时间推进半小时，回复过期不发送；该回归首次通过。发送边界共 46 passed。

全量测试 347 passed in 40.74s，无跳过，包含真实本地 PG 与合成 HTTP/WebSocket 的在线回归。ruff check、format、mypy（35 个源码文件）及 git diff --check 通过。

live composition 已注入动态准备。模型尚未选择 mention，因此此切片只使在线发送出口具备动态解析能力。前序 d117005 的 CI 36571208636 已确认 success，不能替代本切片验证。

未执行真实 QQ 请求。no_cache=true 是协议要求，不保证平台即时刷新或避免查询到发送之间的退群竞态。引用动态解析仍明确拒绝，待解决 SnowLuma 的引用丢失可观测性；不把此限制当作完整功能已完成。
