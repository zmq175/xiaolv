# 验证证据

2026-09-29，测试沿用在线入口和回放入口；合成模型 HTTP 服务、OneBot WebSocket 服务、真实本地 PG。

- 首个在线模型选择 member_1 的测试先 Red（模型无法输出并送达 mention，5 秒外层等待超时）。接入 TextReply、上下文成员引用、结构化解析、运行时传递及 live 群聊能力后，与既有纯文字在线回归一起 Green：2 passed。
- 回放模型输出不在当前上下文的账号先误 confirmed（Red）；增加运行时范围检查后 14 个当时的回放测试通过。
- 在线 member_999、原始 qq:10001、all 三种伪造引用均首次通过拒绝回归，结果 model_error、无查询无发送；与正常 mention 端到端共 4 passed。
- 另补跨会话上下文不能成为通知目标、纯文字空 mentions 不查询成员的回归。
- 全量 353 passed in 44.08s，无跳过；ruff check、format（156 文件）、mypy（36 源码文件）、git diff --check 通过。

模型只看到经过上下文裁剪的 member_ref，解析使用同一份实际发给模型的上下文，不能引用已被裁掉的成员条目；引用不使用显示名。输出去重后沿用动态群成员校验和 outbox mentions 持久化。群聊能力由组合层受信路由开启，模型模块不解析 QQ 会话 ID；私聊维持纯文字输出 schema。

前序 bb8c66b 的 CI 36571741402 已确认 success。真实供应商的结构化输出支持、QQ 通知、自然度均待真实账户验收；本轮未访问付费模型或真实 QQ。有序行内 mention、引用选择及多模态计划仍未完成。
