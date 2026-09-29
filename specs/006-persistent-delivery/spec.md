# SPEC-006：PostgreSQL持久发送状态

状态：Verified（本地PostgreSQL集成）。DeliveryService边界已确认；内部账本自主实现。

## 接口与迁移

DeliveryService保持deliver(request)，status改为async以支持远程数据库；新增start_turn(conversation_id)返回单调递增epoch，recover()清理失联发送状态。注入DeliveryLedger，默认内存回放账本，生产候选PostgresDeliveryLedger使用SQLAlchemy async与psycopg。平台发送在事务外。

Alembic首迁移建立app.conversation_state和app.outbox。outgoing_id全局唯一，payload冲突拒绝；当前文字回放ID已包含会话。后续plan_id/part_index、chat_turns、权限/配额及inbox按对应规格迁移，不预先声称已具备完整调度能力。

## 验收

- AC-001：确认发送后重建service/engine仍查询到confirmed，重复deliver不调用平台。
- AC-002：有效请求先原子认领sending并提交，再调用平台；另一个实例遇到sending返回sending，不发第二次。
- AC-003：同一conversation的start_turn由数据库原子递增，旧epoch拒绝；到期使用数据库时间判断，返回expired。
- AC-004：发送后回执丢失记unknown；重新建实例重放不发送。异常与取消语义沿用SPEC-002。
- AC-005：进程在sending状态失联，只有租约到期后recover标unknown；不将sending重新排队发送。正常终态不受恢复影响。
- AC-006：同ID不同payload拒绝，不能覆盖已确认记录。
- AC-007：不同会话发送互不被网络等待阻塞；事务不跨越平台调用。
- AC-008：缺少迁移/数据库故障时调用失败且不发送，不退回内存模式。

- AC-009：认领返回后再次检查期限；平台等待最多10秒且受剩余TTL压缩，超时归unknown，不自动重发。

## 范围与限制

本切片是持久发送认领，不是完整异步outbox dispatcher：未实现待发队列、调度器租约、权限/预算、提醒任务。status为sending表示仍在处理，unknown表示不能判断远端结果。租约只用于判断失联，绝不授权重发。

确认结果保存失败时数据库仍留sending；恢复后unknown。无法保证远端已经接受的请求可撤销，也不声称跨平台exactly-once。

## 依据

https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
https://alembic.sqlalchemy.org/en/latest/cookbook.html
https://www.postgresql.org/docs/18/explicit-locking.html
