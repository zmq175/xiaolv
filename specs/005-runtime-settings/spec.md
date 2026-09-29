# SPEC-005：启动配置契约

状态：Verified（配置加载接口）。配置公开接口已由用户于2026-09-29确认。

## 接口

`load_settings(environ: Mapping[str, str]) -> Settings`。读取XIAOLV_前缀配置，忽略其他环境变量，拒绝未知XIAOLV键以避免拼写错误被静默忽略。Pydantic v2校验，返回冻结配置；异常ConfigError只报告字段名称，不包含输入值或原始ValidationError。

## 验收条件

- AC-001：空环境默认replay，chat_ttl_seconds=45，queue_max_age_seconds=10，model_concurrency=2，max_reply_chars=200；无外部调用。
- AC-002：环境可显式覆盖以上数字；非数字、非正数、非有限数、队列最大年龄超过TTL均拒绝。
- AC-003：mode=live必须显式提供database_url、model_base_url、model_api_key、model_id、onebot_url、onebot_token；无默认付费模型。
- AC-004：敏感字段采用SecretStr；配置repr、JSON及校验异常不包含密钥或数据库凭据。
- AC-005：数据库只接受postgresql+psycopg URL，模型只接受http(s)，OneBot只接受ws(s)；url不得为空，live字段不得为空白。
- AC-006：未知XIAOLV字段报ConfigError，其他环境变量不影响配置。

提供.env.example和文档，但加载函数不自动读取工作区外文件。使用正式启动入口时由调用者提供环境，不在聊天中修改运行配置。此处校验不等于真实服务连通验收。
