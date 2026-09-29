# SPEC-001实施计划

先确认evaluate_reply_validity这一公共测试边界。确认后记录日期/来源，将状态改Ready，然后写第一个失败测试。

测试文件拟为tests/test_reply_validity.py，实现位置拟为src/xiaolv/domain/conversation/reply_validity.py；文件位置不构成测试断言。用显式时间参数避免真实sleep，无外部依赖。

顺序：到期拒绝 → 有效允许 → 旧epoch拒绝 → 双条件原因优先级 → 时区及非法输入。每一步独立记录Red/Green，禁止先铺完全部测试或实现。

风险：纯判定不能代替发送前数据库原子校验，后续集成规格必须补上该边界。无数据迁移、无外部副作用、无需收费API。
