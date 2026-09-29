# SPEC-009证据

2026-09-29，公开DeliveryService行为验证。

新增构造参数缺失是接口搭建失败；建立字段后仍没有at段为实际Red，修正后OneBot发送测试14 passed。5类非法/跨群/all/私聊/非法账号目标失败→19 passed；重复引用生成2个at失败→20 passed。

真实PostgreSQL测试先出现mentions未持久化导致重建后payload冲突；新增0002_mentions迁移及JSONB保存/比较后11个数据库用例通过。降级后重新升级的既有用例也通过。

组合全套114 passed，包含13个本机WebSocket、20个OneBot发送契约、11个PostgreSQL用例。后续真实QQ通知、群成员同步、退群刷新、LLM选择成员及人物消歧尚未验收。迁移降级会删除mentions字段，只用于测试/有恢复方案时执行。

额外迁移回归：构造0001版本历史confirmed文字记录，升级0002后通过公共发送服务查询/重放仍confirmed且未发消息。数据库测试12 passed。该回归由现有DEFAULT空数组实现直接满足。
