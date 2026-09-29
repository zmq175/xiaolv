# 语音闭环实施证据（进行中）

2026-09-30，沿用聊天回放与配置/日志边界；假结构化模型和假语音执行器，未调用真实TTS或QQ。

- 首个语音回放起初缺少voice_profiles参数而失败；新增VoiceReply、按会话可用逻辑音色选择的结构和VoiceDelivery执行边界后通过。原回合scope/deadline/outgoing_id原样进入替代执行器，文字平台零发送。
- 生成结束时原消息已过期的测试起初confirmed；增加执行入口时效复核后expired且不进入语音执行。
- 语音执行故障起初归类model_error；限定语音调用异常边界后voice_error，不回退文字。第一次文本替换未命中已格式化源码，测试仍失败；核对代码并补齐后通过。
- 超长VoiceReply起初进入执行器；运行时独立校验语音正文非空、长度及逻辑音色非空后invalid_reply。
- 补充回归：允许语音时LLM选文字仍保留有序文字/@/引用，语音执行器零调用；缺执行器返回voice_unavailable；模型自造音色拒绝；等待执行超时仍受原deadline取消。与现有模型/引用专项合计70 passed in 7.30s。另补充生成期间撤权阻止进入语音执行。

静态检查ruff/format、mypy（50源文件）通过。完整回归506 passed in 164.71s，无跳过，包含既有真实本地PG、管理浏览器和合成在线链路。语音配置尚未接入run_live；当前VoiceDelivery只有协议和测试替身，尚无生产实现，不以回放confirmed冒充已成功合成/发送语音。

尚需实现：官方Fish SDK传输层字节限制、SpeechSynthesizer和音色绑定、音频产物、持久合成/费用/并发保护、原生record发送与在线配置、合成后权限/epoch复核及真实音色/QQ验收。不得将收费TTS放进现有严格只读prepare接口。
