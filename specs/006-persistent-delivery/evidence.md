# SPEC-006验证记录

日期2026-09-29。本地真实PostgreSQL 18.6，临时私有Unix socket；每用例独立随机数据库，执行真实Alembic升级，结束删除自己创建的数据库。不安装系统服务、不访问现有业务数据。首次下载多余libxml2依赖遇到404，系统已有该库，经ldd核对无缺库后正常启动；沙箱阻止socket的尝试属于环境错误，不算业务Red。

命令：配置XIAOLV_TEST_DATABASE_URL后，`uv run --offline --locked pytest tests/integration/test_persistent_delivery.py -q --tb=short`。

| 行为 | Red/已有满足 | Green |
|---|---|---|
| 确认后重建service/engine去重 | start_turn未实现 | 1 passed |
| 8实例并发 | 初版直接回归通过；随后epoch事务锁覆盖同会话竞态 | 2 passed |
| 数据库epoch | 旧回合意外confirmed | 3 passed |
| 数据库期限/原因优先 | superseded而非expired | 4 passed |
| 持久内容冲突 | 未拒绝覆盖意图 | 5 passed |
| 丢失回执跨实例 | 共享服务逻辑已满足 | 6 passed |
| 发送进程失联恢复 | recover未实现 | 7 passed |
| 旧进程迟到确认 | 覆盖unknown为confirmed | 8 passed |
| 跨会话/事务不跨平台调用 | 已有短事务满足 | 9 passed |
| 迁移降级/恢复与失败关闭 | 已有数据库异常传播满足 | 10 passed |

共享DeliveryService另增2个红绿测试：认领返回后到期仍发送→改发送前检查；平台无限等待→改剩余TTL内超时并保存unknown。async status改动后原有68个测试仍通过。

最终全套80 passed（含10个数据库集成），ruff/format通过，mypy src通过（16个源文件）。PostgreSQL官方18.6镜像摘要已核对并固定于CI；CI结果在提交后单独核对，不预填通过。

限制：未实现完整pending outbox队列、Inbox、调度租约、权限/配额、人物/知识库以及真实平台。测试以假平台模拟进程失联，不是操作系统kill进程/数据库断电演练。数据库不可用不退回内存；真正灾难恢复仍需后续阶段验收。
