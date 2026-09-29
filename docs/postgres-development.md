# PostgreSQL开发与迁移

依赖通过`uv sync --locked`安装，数据库版本验证为PostgreSQL 18.6。运行端必须显式创建数据库并赋予迁移账号建表/建schema权限；正式应用账号的最小权限与部署脚本后续交付。

迁移通过环境中的XIAOLV_DATABASE_URL读取连接，明确执行`uv run alembic upgrade head`，不会在机器人启动时偷偷迁移。第一次升级创建app.conversation_state和app.outbox。仅测试阶段可用`uv run alembic downgrade base`清空这两张表；它会删除发送记录，生产禁止用作普通回滚方式。

测试使用独立数据库xiaolv_test，连接用户需要CREATEDB权限。设置XIAOLV_TEST_DATABASE_URL为该库的postgresql+psycopg URL，然后运行`uv run pytest`。每个集成用例创建随机测试数据库、执行迁移、验证公共服务行为，最终删除该随机库；不会清空指定的现存库。DSN未设置时集成测试显式skip，不能称为数据库验证通过。CI提供固定镜像的临时PostgreSQL，自动运行这些用例。

当前持久账本使用短事务原子认领，平台网络调用发生在事务之外。进程失联遗留sending状态只会在租约超时后变为unknown，不重发；需由后续管理核验功能处理。已确认或未知结果不会在重复提交时再发一条。

实现是持久发送保护切片，尚不是完整异步outbox调度系统，也没有完成生产备份恢复演练。应用连接池须设置有界超时并保持隐藏SQL参数，禁止把DSN、SQL参数或原始消息写入公开日志。
