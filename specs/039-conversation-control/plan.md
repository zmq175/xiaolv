# 实施

沿用管理HTTP、DeliveryService和聊天入口边界。启动时登记已配置路由，不覆盖已有开关；清单表示已登记会话，不声称实时连接。GET /admin/api/conversations采用conversation_id游标、默认20上限50；PUT /admin/api/conversations/{id}要求enabled、expected_version及幂等键。独立管理进程从PG读取，不持有QQ连接。

先完成持久表与HTTP变更并验证旧epoch失效，再将权限读取及登记接入run_live，最后实现网页与浏览器验证。停用事务和发送认领统一先锁conversation_state再读/改策略；同会话幂等键永久记录请求哈希与响应。事务提交之后已认领发送定义为在途，无法原子控制远端平台。
