# SPEC-014 验证证据

2026-09-29。14个真实PostgreSQL集成用例、11个配置用例；全量247 passed（无skip），ruff/format/mypy 30个源文件通过。所有价格为合成价格，没有调用收费服务。

红绿链：预算未接入导致不足额仍silence→明确budget_denied且HTTP零调用；settle未实现导致可用额度下model_error→按实际usage结算并重建读取；超预留未暂停月池→记录真实金额并blocked；11种浮点/非法/精度溢出/缺标识配置未拒绝→构造时拒绝；历史月份审计参数缺失→支持按历史月查询并验证原价原月结算。

补充回归：未知usage跨连接重建仍保留；两个独立连接池争抢最后一份额度只能一个调用HTTP；相同report重放不重复扣费，冲突report拒绝；缓存折扣按合成价格向上取微元；取消时预留不退；配置漂移不能提升已有月池限额；真实子进程在HTTP请求开始后SIGKILL，重建读取仍保留预留；注入model_calls表不可用故障，HTTP零调用且预留事务回滚。

AC映射：001 insufficient_monthly/known_usage/rebuilding/database_failure；002 unknown_usage/cancelled_model/SIGKILL；003 shared_budget/replayed_audit；004 late_settlement（历史fixture使用2001-02月与old-price，对比当前new-price99元合成价）/different_configured_limit/config参数化；005 actual_cost_over_reservation。测试通过TextRuntime、公开账本审计/snapshot及配置观察，SQL仅用于历史数据初始化与故障注入，不读取内部表断言。

命令：设置专用`XIAOLV_TEST_DATABASE_URL`后运行`UV_CACHE_DIR=/tmp/xiaolv-uv-cache uv run --offline --locked pytest tests/integration/test_model_budget.py -q --tb=short`及全量`pytest -q --tb=short`。fixture只创建/删除随机测试数据库。配置测试`pytest tests/test_budget_policy.py -q --tb=short`。SIGKILL故障只杀测试自行创建的子进程。

限制：当前按DB UTC自然月；金额numeric(20,6)。供应商价格/汇率、隐藏token开销及实际消费上限尚未配置/验证。预算是可绑定的基础组件，在线启动接线尚未完成，不能宣称生产全链路已受月预算控制。月池固定额度冲突拒绝；管理变更、人工账单核对和未知预留释放、70%/90%分级策略仍待后续实现。只有模型token账本，搜索/TTS等尚未接入。

预留估计包含请求messages/schema的序列化字节及1024开销余量、512输出token；不是供应商账单上界证明。超预留会冻结月池但不撤销已发生费用；200元总预算还必须扣除服务器与其他费用，并设置供应商侧限额。migration 0005降级会删除审计与预算表，生产禁止无备份降级。

审查补充：gateway模型没有对应报价时HTTP零调用；注入结算更新失败后，已提交的调用前预留仍保留，不能因结算失败退回额度。这两项均通过公开回放/审计验证。
