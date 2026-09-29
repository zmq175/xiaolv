# 验证证据

2026-09-29，TextRuntime → ChatCompletionsModel → 外部 StructuredGenerator 替身，观察模型真实接收的 JSON；未直接测试私有上下文方法。

- 可见引用目标：Red 为没有 message_ref，增加稳定上下文引用及 replies 后 Green。
- 重复消息 ID：Red 为静默选择一条 resolved；统计当前范围内重复 ID，返回 ambiguous/null 后 Green。即使某个重复条目裁剪掉，已知歧义仍不消除。
- 元数据长度：最初普通长消息回归已通过；增加 100 个引用段压力输入后 Red，实际 JSON 长度 15938。将引用元数据纳入裁剪并每次重算关联后 Green。
- 被裁剪原文转 missing、未知原文 missing 首次即通过。裁剪场景最初 180 段未达到上限，修正测试数据为 200 段以实际触发裁剪，未声称该测试准备错误是产品缺陷。
- 定向测试 5 passed；格式、静态检查另见全量记录。
- 全量 358 passed in 45.62s，无跳过；ruff check、format（160 文件）、mypy（36 源码文件）及 git diff --check 通过。

参与和回复模板都说明 resolved/missing/ambiguous，避免把缺失引用误解为“在回复机器人”。解析只使用现有会话快照，不跨会话补取，不发生网络查询；未执行真实模型或 QQ 请求。

后续发送核对线索：参考 SnowLuma 提交 1ef9a2c33023b5fcb400865c8281d2dfd190540b 的 modules/message-actions.ts 中 cacheSelfSentMessage 将转换后的 MessageElement 转成 OneBot 段并缓存，get_msg 可读取该事件。因此可用发送后的读回检查识别被丢弃的 reply 段；读回缺失或不一致只能记未知且不重发，不能据此证明客户端显示。该发送核对尚未实现。

前序 6c871f2 的 CI 36572375795 已确认 success，不将其当成本切片的 CI。
