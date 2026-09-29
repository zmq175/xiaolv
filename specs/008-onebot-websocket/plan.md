# 计划

连接与发送→事件/echo分流→并发乱序→断连与超时→队列边界与关闭。每项通过本地实际WebSocket协议验证。只在请求进入socket发送之前能明确not_sent，其后异常保守unknown。
