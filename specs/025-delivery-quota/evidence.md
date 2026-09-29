# 验证证据

2026-09-29，沿用 DeliveryService、配置和在线入口。

- PG 四实例独立消息竞争一条额度：先缺少 DeliveryPolicy（Red）；增加策略、迁移与会话行锁内计数后，结果 1 confirmed + 3 rate_limited（Green）。
- 配置边界先因缺少 delivery_policy 属性失败；接入 JSON 配置后 Green。
- 重启仍计 unknown、not_sent 释放、不同会话独立、冷却后不补发旧限流消息、滚动窗口恢复，4 个配额定向用例通过，新增回归首次即通过。
- 在线真实本地 PG + 合成 HTTP/WebSocket，两轮分别 confirmed/rate_limited，平台仅一次发送；首次通过。
- 补迁移降级/升级后 confirmed 和拒绝记录仍不重发，非法配置拒绝的回归。
- 全量 390 passed in 54.22s，无跳过；ruff check、format、mypy（37 源码文件）和 git diff --check 通过。

发送计数基于 PG 时钟与 claimed_at，不由各进程时钟计数；既有会话行锁将配额判断和 outbox 插入串行化，网络 IO 在事务外。明确拒绝的记录不占额度；unknown 不退还额度。默认仅在线组合启用，未传策略的隔离账本测试和本地回放维持其原测试范围，不假称离线内存账本实现了分布式配额。

默认 5 秒/60 秒 6 条是待实测调优起点，所有实例应使用相同配置。保护在模型生成后的最终发送位置，尚不能避免已限流回合的模型费用；主动日配额、跨进程模型并发和多 part 计划另行实现。

前序 24fbb16 的 CI 36573900452 已确认 success。本轮无真实 QQ、付费模型或云部署。
