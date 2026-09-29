# SPEC-010 验证证据

2026-09-29，OneBotIngress.receive公开入站边界，合成事件。

红绿链：群聊未实现→1通过；临时私聊隔离失败→2；meta/notice/request/self消息未过滤→7；缺少parts→8；无效消息未拒绝→17；无时区时间未拒绝→18；历史/未来标记缺失→20。每组对应单一行为，修正后再推进下一项。

当前20个归一化用例全部通过，覆盖身份与会话键、群/私聊/临时会话、at/reply/image/face/record、时间有效性。媒体仍是引用；未登录QQ，未下载媒体或调用视觉/语音模型。SnowLuma源代码契约不替代真实平台联调。

实际运行命令：`UV_CACHE_DIR=/tmp/xiaolv-uv-cache uv run --offline --locked pytest tests/test_onebot_ingress.py -q --tb=short`。PG用例设置`XIAOLV_TEST_DATABASE_URL`指向专用xiaolv_test基础库，由fixture新建随机数据库；未配置会skip，不能计为数据库验收。组合运行`uv run --offline --locked pytest -q --tb=short`，另执行`ruff check .`、`ruff format --check .`、`mypy src`及`git diff --check`。

AC映射：001群聊身份、002私聊/临时会话、003非消息/自身过滤、004有序媒体parts、005参数化非法输入/无时区、006历史/未来时间。全部在test_onebot_ingress.py通过receive断言。
