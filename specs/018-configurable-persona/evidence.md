# 验证记录

2026-09-29，MaiBot参考版本170453d629ba2c72259c858c565bbf0d11060d33。分析见docs/architecture/09-persona-prompts.md。

## 红绿

- `test_configured_identity_is_used_for_participation_and_reply`：配置入口因未知bot_profile失败→引入BotProfile、版本化模板和模型参数后通过。参与/回复请求均包含管理员新姓名、别名和人设，无固定小绿；自定义花括号原样保留，长度提示80而非写死200。
- `test_live_uses_configured_persona_and_reply_limit`：独立模型边界通过后，在线接线仍使用默认小绿导致失败→run_live传入同一profile和max_reply_chars后通过。CLI子进程配置测试相应支持嵌套profile JSON，复验通过。
- 非法名字/别名/人设/风格/未知字段/JSON的10项配置回归首次运行通过。群友要求改名仅出现在user消息，管理员资料仍在system；该测试只证明输入来源隔离，不宣称真实模型一定服从。
- 原有长上下文测试以单个“长”字判断正文未进入system，碰到合法新风格文案“长篇总结”误报；改为识别20字连续的合成正文片段，保留来源隔离、截断标记、长度与近期消息断言。两个本机端口用例在默认沙箱无法bind，经本机网络权限运行完整套件复验。

AC-001/003/004 → test_chat_model的configured_identity及test_live的configured_persona；AC-002 → test_settings的invalid_persona/persona_json。设置本机PG测试DSN执行 `uv run pytest -q --tb=short`：295 passed in 38.87s，无跳过。ruff check、ruff format --check、mypy src均通过。

## 范围

未调用真实模型或登录QQ；提示质量/拟人效果不能由合成请求测试证明。当前配置重启生效，尚无管理端发布、人设版本审计或会话风格覆盖。腾讯文档尚未同步本增量。
