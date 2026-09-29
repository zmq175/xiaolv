# 实施与SDK核验

2026-09-30，先核验官方SDK与原生平台源码，再按一条行为红→绿推进。不要把全部语音功能挪到Skill，也不要随机选择语音。

1. 聊天入口验证模型明确选择媒介；保留原文字/@/引用结构。定义供应商无关意图、SpeechRequest和AudioArtifact，绑定会话/回合/期限。
2. 以合成HTTP服务接官方Fish SDK，验证音色映射、超时、字节上限和失败不重试。TTS是可能收费的执行阶段，区别现有只读发送准备；先完成持久调用/预算保护再接生产配置。
3. 受限音频产物与原生record出口，复用发送认领、未知回执和动态权限。优先由SnowLuma适配端处理平台codec，业务层不重写Silk编码器。
4. 完整回放、供应商替换、文字零合成、停用/迟到、幂等和降级故障矩阵；真实账号验收单独保留。

官方SDK可行性证据见sdk-probe.md；可复现脚本tools/probes/fish_sdk_contract.py只使用合成httpx传输，不调用公网API。当前未添加生产依赖，避免把尚未使用的SDK混入运行路径。

## 当前接口落地

VoiceReply只包含speech_text与逻辑voice_profile；模型按当前会话允许音色获得可空voice结构，选语音时parts为空且不混合引用，选文字时保留有序parts。普通无语音配置的会话结构保持现有行为。额外音色说明和schema进入现有上下文token预算。

TextRuntime在原deadline内调用VoiceDelivery.deliver(candidate, reply, outgoing_id)，缺执行器明确voice_unavailable，绝不把正文当文字发出。该接口的生产实现须拥有持久合成生命周期和费用预留，并最终调用DeliveryService；当前仅回放替身，下一步从真实本地PG与合成供应商边界逐条验证这些约束。

## 持久合成执行

SpeechExecution从聊天入口接收原始回合和VoiceReply，使用SpeechSynthesizer协议取得SpeechResult，再调用受保护的音频分发边界。当前供应商和分发仍为测试替身；生产分发必须接DeliveryService，不能直接调用平台。

PostgresSpeechLedger以speech:outgoing_id认领，保存请求哈希、会话/epoch/期限、供应商/模型/价格版本/音色绑定版本。金额复用app.budget_periods，调用审计独立app.speech_calls，不伪装为token使用量。已知charged_amount才能结算；没有可靠金额或发生失败/取消则保留预留。合成结束后再读取权限、epoch和期限，最终原生出口仍须再校验。

当前SpeechPolicy.reservation_amount是管理员绑定价格策略的保守预留额，不是Fish Audio价格或真实账单。上线前须补供应商实际计价单位、预留计算/校准及未知金额核对入口；不因SDK返回音频就编造charged_amount。金额超过剩余池时拒绝新请求，真实费用超出预留导致池超限时阻止后续调用。

可注入现有PostgresModelCapacity作为独立speech-model池（首轮容量1）。先等待名额再预留费用，跨进程租约沿用原deadline和崩溃回收机制。默认无容量对象仅用于隔离回放，生产组合必须显式绑定共享容量。
