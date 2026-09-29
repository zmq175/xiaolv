# 验证证据

2026-09-29，沿用用户已确认的回放入口与DeliveryService。没有新增测试边界提问。

- AC1：`tests/test_ordered_text.py::test_delivery_preserves_inline_mention_and_separate_quote` 首次因缺少TextPart接口导入失败；实现后1 passed。断言实际OneBot RPC消息数组，包含引用头、文字、at、文字。
- AC2：参数化非法意图先出现5 failed / 2 passed（其中正常用例和已有成员拒绝通过），增加服务层结构校验后7 passed。覆盖正文不一致、成员不一致、不支持段、仅提及、段数过多及重复提及。校验在只读准备之前，失败仍通过统一账本记终态。
- AC3：回放用例先因旧链路把at移到正文前而失败，接线parts后8 passed。长度保护继续作用于经一致性校验的拼接正文；没有将单段长度误作整条长度。
- AC4：真实PG重建服务测试先因未持久化parts报payload conflict；迁移和存储接线后1 passed。相同请求确认但不重发；改变at位置、保持相同正文和成员时拒绝复用编号。
- 静态检查首次发现测试格式及适配器局部变量parts与引用读回重名导致类型冲突；修正后ruff check、77文件format检查及mypy 39源文件通过。

AC5：全量真实本地PG、合成HTTP/WebSocket回归404 passed in 66.48s，无跳过。执行命令为设置专用XIAOLV_TEST_DATABASE_URL后`uv run --offline --locked pytest -q --tb=short`，包含既有迁移、旧消息兼容、成员核实、引用读回、过期和配额用例。

模型结构化输出仍沿用原text/mentions格式，本规格没有声称模型在线生成交错消息已完成。媒体ReplyPlan、真实QQ显示和通知效果未验收。迁移降级保护未单独做含有序记录的执行测试。未调用收费模型、真实QQ或云部署。
