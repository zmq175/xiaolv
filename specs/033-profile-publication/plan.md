# 实施

按公共HTTP逐行为红绿：草稿→发布基本流程；并发版本；持久幂等重试；回滚与错误边界。认证复用原会话/CSRF规则；事务和存储放独立发布模块，避免管理路由堆SQL。

新增0011迁移：admin.profile_state单行、admin.profile_mutations幂等回执、app.bot_profile_releases不可变快照及app.bot_profile_current指针。停止聊天/管理后才允许降级，降级会删除控制面配置；备份与运行时回退需显式运维决策，不在线偷偷降级。
