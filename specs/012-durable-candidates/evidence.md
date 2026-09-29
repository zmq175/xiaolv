# SPEC-012 验证证据

2026-09-29，真实本地PostgreSQL、假模型/平台。

红绿链：run_once未实现→首个入站到发送通过；缺少上下文→群内合并上下文通过；同群忙时仍发送→租约排他及其他群并发通过；队列过时仍回复→模型调用前丢弃通过；补充消息延长TTL→保留首次期限通过；无限延后ready→固定合并上限通过；过期候选污染新话题→替换过期候选通过；取消后租约残留→finally清理通过。

补充回归：8个并发worker对一个沉默候选仅调用一次模型；默认关闭和历史消息不调用模型；重建数据库连接后可消费未认领候选，已完成回合不重复。11个worker集成测试通过。

全量组合159 passed（无skip），mypy 25个源文件通过。进程强制终止后的租约自然过期/旧worker隔离尚需故障测试，所以状态仍为Implementing；不能将连接重建测试称作完整进程崩溃演练。还需要处理过期running回合的审计状态及配置非法值验证。动态权限/配额、相关性复核、DEFER和真实平台循环仍在后续范围。

实际运行命令：`UV_CACHE_DIR=/tmp/xiaolv-uv-cache uv run --offline --locked pytest tests/integration/test_chat_worker.py -q --tb=short`。PG用例设置`XIAOLV_TEST_DATABASE_URL`指向专用xiaolv_test基础库，由fixture新建随机数据库；未配置会skip，不能计为数据库验收。组合运行`uv run --offline --locked pytest -q --tb=short`，另执行`ruff check .`、`ruff format --check .`、`mypy src`及`git diff --check`。

后续补齐：真实独立Python子进程认领回合后SIGKILL，确认租约内不能接管，到期recover返回1并标记expired，再次recover为0，新消息获得epoch2且旧消息不重新生成。时钟落后30秒的旧worker迟到结束时，不会释放新worker租约或覆盖expired审计结果。CandidatePolicy 10种非法/可变参数先全部失败，校验后全部通过。现在13个worker集成用例+10个配置用例通过；前述“尚需故障测试”已由这两项覆盖，状态改为Verified。

AC映射：001启用首条消息/默认关闭/历史/重复；002同群合并隔离上下文；003并发沉默消费及不同群并行；004队列年龄/首次TTL/最大合并等待/过期替换；005慢模型期间新入站/SIGKILL后新候选；006重建连接/取消/SIGKILL审计/迟到旧worker；007参数化CandidatePolicy校验。所有行为通过入站与ChatWorker或配置边界观察，未直接查询内部表作断言。
