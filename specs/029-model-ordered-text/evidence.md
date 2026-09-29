# 验证证据

2026-09-29。沿用在线入口，使用真实本地PG、合成模型HTTP与OneBot WebSocket，不mock内部模型/发送实现。

- AC1首个失败用例：模型HTTP返回parts，旧在线链路得到model_error而非confirmed（1 failed）。实现严格schema、可见成员解析及live接线后1 passed；原生消息数组包含reply、text、at、text，成员列表查询发生一次。
- AC2参数化覆盖裸账号、未知member_ref、重复提及、不支持image、空parts、201字正文、33个段。复用SPEC-028及既有长度保护，没有为了制造失败而移除原有检查。这些保护用例属于首次运行验证，不能冒充新增红绿循环。
- 在线专项35 passed in 39.23s。ruff check、77文件格式检查和mypy 39源码文件通过。修正测试观察条件后完整回归412 passed in 68.88s，无跳过，覆盖AC3；git diff --check通过。

前序提交592fb44的GitHub CI 36578684798已核实success；此结果不代表本次未推送改动的远程验证。

首次全量411 passed / 1 failed（68.56s）：已有心跳/空chunk超时用例的stream.closed未置位。单独复验2 passed，说明未稳定复现；不能据此断言生产流清理有误或环境故障。原测试只有30ms包括SDK构造HTTP请求和打开流，无法区分是否实际进入读取。改为200ms初始预算、至少1秒心跳序列，并明确断言stream.started及stream.closed，仍要求无真实内容时超时且不发送；生产超时参数未改。此修改增加测试启动余量并强化观察，不删除关闭断言。

无新增依赖及数据库迁移。线上默认结构从text/mentions变为parts；供应商需支持该JSON schema的对象数组和引用定义，真实供应商兼容性仍待凭据联调。已有独立适配模式保留；生产live入口启用有序结构。多模态计划和真实QQ视觉效果未完成，未调用收费服务。
