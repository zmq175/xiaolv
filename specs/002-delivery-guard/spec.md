# SPEC-002：原生发送出口保护

状态：Verified（仅回放内存实现）。2026-09-29用户确认DeliveryService公共测试边界及内部细节自主决定。

## 公共接口与范围

异步 `DeliveryService.deliver(request)` 返回发送结果；`status(outgoing_id)` 查询本实例保存的结果。注入平台适配器、时钟和当前epoch读取函数。平台适配器负责真实发送，不经过MCP。先用内存状态实现回放可验证的出口，数据库持久化另做规格，不能将内存去重称作重启安全。

DeliveryRequest包含唯一outgoing_id、conversation_id、expires_at、generation_epoch和text。适配器send(request)返回confirmed或unknown；明确发送前失败使用NotSent异常，通用异常视作unknown。调用者取消也保守记unknown，并向上传播取消，不自动重发。

## 验收条件

- AC-001：到期后不调用平台，返回expired。
- AC-002：有效请求调用原生平台，返回confirmed。
- AC-003：旧epoch不调用平台，返回superseded。
- AC-004：相同outgoing_id重复或并发提交，只发送一次，后续返回已记录结果。
- AC-005：网络未知结果记unknown，不自动重试；相同ID重新提交仍不发送。
- AC-006：同ID不同内容属于冲突，抛ValueError，不能悄悄发送/复用另一条结果。
- AC-007：排队等待期间过期，获得发送机会后拒绝；每次平台调用之前读时钟和epoch。
- AC-008：明确未发送返回not_sent，首个切片不自动重试；取消中的请求记unknown并传播取消。

## 非目标

不提供跨进程、跨实例及重启幂等，不实现PG事务/租约/权限配额、不接真实QQ。内存状态生命周期由回放实例控制。本接口为内部服务入口，管理员授权与内容预算必须在生产接线前加入。平台已接受后无法撤销。
