# SPEC-011 验证证据

2026-09-29，真实本地PostgreSQL 18，测试只在自动新建并销毁的随机数据库运行。

TDD：入口未实现失败→重建连接仍可读1通过；重复主键异常→幂等2通过；context缺失→版本与epoch隔离3通过；非法窗口5种失败→窗口校验8通过。已有实现的补充回归验证不同群同消息ID、8个并发重复请求、窗口排序、ignored/历史保存。注入数据库revision写约束故障后，公开context仍为0/空，证明事务回滚而非伪成功。

13个入站数据库用例通过。context使用单语句快照；候选调度读上下文时持有会话短事务锁。队列行为由SPEC-012另行验证。未以此声称长期人物/关系记忆或真实QQ输入已实现。

实际运行命令：`UV_CACHE_DIR=/tmp/xiaolv-uv-cache uv run --offline --locked pytest tests/integration/test_incoming.py -q --tb=short`。PG用例设置`XIAOLV_TEST_DATABASE_URL`指向专用xiaolv_test基础库，由fixture新建随机数据库；未配置会skip，不能计为数据库验收。组合运行`uv run --offline --locked pytest -q --tb=short`，另执行`ruff check .`、`ruff format --check .`、`mypy src`及`git diff --check`。

AC映射：001 test_message_context_survives_rebuilding_connection；002 test_duplicate_does_not_refresh_original_content_or_time；003 test_same_message_id_is_isolated_by_conversation；004 test_concurrent_duplicate_delivery_registers_once和test_context_revision_counts_new_messages_without_advancing_turn_epoch；005 test_ignored_frames_leave_no_context_but_history_is_preserved；006窗口非法值/稳定顺序及test_database_failure_rolls_back_message_and_revision。
