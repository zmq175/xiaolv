# SPEC-013：可替换文字模型与有界流式协议

状态：Implementing。沿用已确认的回放入口、配置边界；HTTP为外部服务替身，不mock自身模块。

`ChatCompletionsModel`实现ConversationModel：参与判断返回respond/silence，选择respond后才生成文字。通过`StructuredGenerator`接口调用模型服务。首个`ChatCompletionsGateway`实现Chat Completions SSE协议，base_url/key/model由管理员显式提供，无默认收费模型。每轮至多参与和生成两个请求，沉默只用一个请求。

- AC-001：标准认证/模型/结构化输出请求，经TextRuntime生成完整文字并进入统一发送；文本分片不直接发QQ。输入只包含本会话上下文，群友内容放user消息而非system角色。
- AC-002：参与判断silence不生成；action和reply严格校验，空白/超长、非法字段/类型、缺少stop/DONE、截断length、拒绝、工具调用或HTTP错误均不发送。
- AC-003：总期限覆盖排队/连接/读取；首次内容等待12秒、内容停顿8秒为可配置初值。仅心跳或空片段不延长等待，持续慢流仍受原始TTL约束。取消关闭流且向上传播。
- AC-004：单进程共享网关并发上限默认2；等待名额过期不得发起新请求。HTTP不自动重试、不跟随重定向，异常正文/密钥不进入业务结果。
- AC-005：响应字节及请求上下文有界；usage可缺失（不当作0费用），保留未来计费接口，月预算预留在后续实现。模型供应商计费和真实输出质量需要live验收。
- AC-006：配置拒绝无效URL/模型/密钥及非法限额；首版只支持声明的json_schema能力，不自动降级兼容未知供应商。不同供应商可替换StructuredGenerator，TTS/视觉/工具接口不塞进文字协议。

协议依据（2026-09-29核对）：[Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)、[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)。这是协议适配，不是指定用户购买OpenAI模型。不声称所有兼容服务支持相同选项。端点使用HTTPS；HTTP仅允许本机开发地址。
