# 05 平台适配、多模态与语音接口

版本：v0.1，2026-09-29。已确认：LLM决定是否用语音回复以及说什么；TTS供应商可更换。基础语音能力不是必须先触发某个Skill才能使用。

## 1. 平台接口

PlatformAdapter是应用内直接实现的平台适配代码，不是MCP客户端或MCP服务器。连接与重连、事件订阅、消息接收、发送、媒体上传下载、回执以及平台查询/操作均通过它直接访问平台协议或SDK。QQ首个实现直连SnowLuma/OneBot的网络接口；其他IM各自使用官方SDK或协议适配，均不经过MCP。领域层只接收标准事件和结果，不依赖QQ群消息JSON。另提供ReplayAdapter用于无QQ账号的回放与故障测试。Native Tool Calling只用于LLM需要主动选择的平台动作，不承担后台事件接收；普通发送由ReplyPlan和DeliveryService驱动。

```python
class PlatformPort(Protocol):
    async def capabilities(self, conversation_id: str) -> PlatformCapabilities: ...
    async def receive(self) -> AsyncIterator[ChatEvent]: ...
    async def fetch_media(self, media_ref: MediaRef, deadline: Deadline) -> MediaArtifact: ...
    async def send(self, envelope: DeliveryEnvelope, deadline: Deadline) -> SendReceipt: ...
```

以上为接口草图，导入、类型定义、测试和具体方法签名在P0实现。能力矩阵区分群/私聊的文字、引用、@、图片、表情包、语音、撤回、历史查询；unsupported必须显式返回，不静默丢失片段。

SnowLuma需要NTQQ客户端和相应运行环境，不能当成独立QQ协议登录器。其连接恢复不等于应用拥有可靠历史重放；支持补历史时标记backfill并禁止旧消息触发即时回复。[SnowLuma实现介绍](https://snowluma.github.io/zh/docs/guide/introduction)

事件去重优先采用平台原生稳定ID；针对哈希消息ID，增加会话、发送者、时间和规范化内容指纹辅助检测。发生相同平台ID但内容冲突时保留并告警，不能误删。引用解析在适配器映射到内部消息ID；识别不出的消息保留unsupported段以便排查，不丢掉整条事件。

## 2. 多模态能力范围

| 类型 | 接收 | 回复 |
|---|---|---|
| 文字、@、引用 | 标准化并保留回复关系 | LLM选文本和目标，平台转换 |
| 图片 | 拉取、校验、缩放、按需视觉理解/OCR | 可发送已授权图片；绘图需单独已发布能力 |
| 表情包 | 保留原图/动图，缓存含义与适用场景 | LLM从可见候选ID选择，禁止编造文件路径 |
| 语音 | 获取音频、必要转码、ASR | LLM输出语音意图，经TTS生成再发送 |
| 视频/其他文件 | 识别类型并明确能力状态 | 不因平台支持发送就承诺已实现内容理解 |

MaiBot源码可见ASR和voice组件收发，不能据此推断它内置了所有TTS供应商。小绿按用户确认增加完整的供应商可替换TTS契约。参考基线：[MaiBot语音识别](https://github.com/Mai-with-u/MaiBot/blob/170453d629ba2c72259c858c565bbf0d11060d33/src/common/utils/utils_voice.py)、[消息组件](https://github.com/Mai-with-u/MaiBot/blob/170453d629ba2c72259c858c565bbf0d11060d33/src/common/data_models/message_component_data_model.py)。

## 3. 媒体不能堵塞入站

先保存ChatEvent和媒体引用，再异步获取/理解。事件正文初始为带状态的占位，不把未识别语音当成用户说了“语音消息”。直接@或回复小绿的语音优先ASR；普通群语音按参与候选与媒体预算处理，防止所有音频都无条件计费，同时保留必要上下文观察。

理解完成更新消息内容版本和会话revision；只有原事件仍在时效内才唤醒聊天候选。迟到的ASR可供后续授权记忆处理，但不补发旧聊天回复。视觉/OCR/ASR的文字都属于不可信消息内容，不能覆盖系统指令。

媒体表包含 media_id、scope_id、hash、mime、size、duration、width/height、storage_ref、source_event_id、expires_at、derived_from、status。缓存按scope+hash+处理器版本隔离；摘要沿用源消息权限。下载限制体积、重定向、时长和解码资源，禁止把外部URL直接当宿主文件路径。

## 4. 语音基础契约

```python
class SpeechSynthesizer(Protocol):
    async def synthesize(
        self, request: SpeechRequest, context: ExecutionContext
    ) -> AudioArtifact: ...


class SpeechTranscriber(Protocol):
    async def transcribe(self, audio: AudioArtifact, context: ExecutionContext) -> Transcript: ...
```

SpeechRequest字段为 speech_text、voice_profile、style_hint、language、max_duration_ms；ExecutionContext包含turn_id、deadline、scope与预算reservation。AudioArtifact为media_id、mime、codec、sample_rate、channels、duration_ms、size_bytes、content_hash；不携带长期供应商访问密钥。Transcript包含文本、语言、可选时间段、处理器版本、状态；供应商不提供置信度时明确为空，不能捏造。

音色使用逻辑名 xiaolv_default，管理配置映射到具体provider voice ID。更换供应商时重新试听映射，不要求LLM知道各平台音色编号。style_hint限制在casual/calm/cheerful等白名单，供应商不支持时回落基础风格；不允许模型构造任意SSML、URL或代码参数。

TTSProvider只做供应商请求与结果下载；AudioNormalizer负责受限进程转码，PlatformAdapter负责QQ所需封装和媒体上传。具体codec由目标适配器实测能力决定，不在业务层假定所有渠道支持同一种格式。转换失败归类unsupported或transcode_failed，不能直接谎报已发语音。

## 5. 模型决策与程序约束

LLM输入包含群媒介偏好、平台能力、允许音色与剩余语音预算；输出VoicePart或TextPart。程序不会随机决定发语音，也不会擅自将回复改为朗读。合成是确定性执行阶段，不再为“是否应该语音”额外启动第二个Agent。

语音流程：校验ReplyPlan → 预留费用 → synthesize → 校验时长与内容归属 → 转码 → 最终相关性/TTL复核 → outbox。合成前与合成后都检查同一回合deadline；过期产物清理，迟到回调仅审计。TTS取消不保证供应商不计费，保留用量核对任务。

预算初值每条最多20秒、每轮一个voice part、全局TTS并发1；这是限制而不是强迫使用语音的比例。超时或失败可在剩余预算内让LLM重规划一次，或者按已允许的same_text发送原speech_text；不做无依据的语义改写。部分发送成功后不再补发同内容文字，unknown结果也不触发重复降级。

合成缓存键包含文本、音色映射版本、供应商模型、风格、语言与scope；不得跨会话复用含私密信息的结果。短期缓存可减少相同测试请求费用，但在线聊天不因命中缓存跳过有效期检查。

## 6. Skill/MCP如何使用语音

讲故事、朗读等Skill可指引LLM生成VoicePart；它不自行连接QQ或持有TTS密钥。若某供应商通过MCP提供合成，编写McpSpeechProvider实现同一SpeechSynthesizer；生成音频后仍走统一媒体和发送流程。

通用CapabilityGateway可提供受限synthesize_speech工具供需要音频文件的工作流调用，但普通语音回复直接materialize VoicePart即可，不强迫模型先调用工具再决定怎么发。产物必须携带media_id，聊天模型不能指定任意输出路径或复用其他会话媒体。

## 7. 表情包学习与媒体验收

表情包候选从观察到的媒体提取标签、语境与来源，去重后进入候选库。首版发送库由管理员审核启用，按会话或明确共享范围发布；管理端以后可配置自动审核规则。LLM选择候选ID和场景，不允许用表情库当成跨群原图泄露出口。

P0/P2实测覆盖群与私聊语音收发、格式转换、撤回后媒体失效、TTS超时、不支持音色、平台发出但回执丢失、LLM选文字时没有TTS调用、换provider后聊天节点不改代码、同内容降级不双发。QQ客户端/SnowLuma版本与样本文件哈希写入验证记录；源码支持不等于已通过实际发送测试。

## 参考资料地址

SnowLuma实现介绍：https://snowluma.github.io/zh/docs/guide/introduction

MaiBot语音识别：https://github.com/Mai-with-u/MaiBot/blob/170453d629ba2c72259c858c565bbf0d11060d33/src/common/utils/utils_voice.py

消息组件：https://github.com/Mai-with-u/MaiBot/blob/170453d629ba2c72259c858c565bbf0d11060d33/src/common/data_models/message_component_data_model.py

## 8. 原生 @ 指定成员

新增明确要求：小绿能够发送真正的成员mention，不能只拼“@昵称”文本。是否@、@谁由LLM结合回复对象决定，程序校验目标是否为当前群可解析成员；默认不每条回复都@，也不自动开放@全体。

TextPart升级为有序segments，其中包含TextSegment(text)和MentionSegment(target_ref)。target_ref来自服务端提供的当前会话成员候选，解析到内部Account，再由适配器映射平台ID；LLM不能凭空生成QQ号，也不能仅按显示名匹配。普通名称含@符号仍是文字，不触发通知。原来的text字段可作为纯文字简写，规范化后统一转segments，schema_version随实现升级。

示例：一个TextPart的segments为 [{"kind":"mention","target_ref":"member_17"},{"kind":"text","text":" 你刚才说的是这个吗？"}]。它是一个消息part，不能把mention和正文各计一次发送。QQ适配器转为OneBot的 {"type":"at","data":{"qq":"目标账号字符串"}}，后接text消息段。引用回复与@是独立能力，不假设引用一定通知被引用者。

发送前校验成员映射、会话范围和通知频率；成员已退群或消歧失败时不改@其他人，可按策略仅保留正文或请LLM重规划。@全体作为单独能力默认禁用，需要管理员明确授权且平台允许；不能因识别失败把空ID/0映射为all。私聊中不发送群mention段。语音需要@时，LLM可明确安排一条mention文字part加一条voice part，受同一轮2条上限约束，不由TTS自动念出QQ号。

源码核查：SnowLuma的element-codecs.ts实现了at段双向转换。MaiBot也有AtComponent和构造方法，因此这里只确认小绿必须支持，不能断言MaiBot整体不支持。尚需实际QQ收发验收。

源码地址：https://github.com/SnowLuma/SnowLuma/blob/1ef9a2c33023b5fcb400865c8281d2dfd190540b/packages/onebot/src/event-converter/element-codecs.ts

动态发送准备见 SPEC-021：通过 get_group_member_list(group_id, no_cache=true) 核实成员，严格检查响应和每条记录的群范围。不能用 get_group_member_info 返回了匹配账号作为在群证明：参考版本可能对查不到的账号返回占位资料。准备成功后由 DeliveryService 再检查期限与 epoch 并认领发送。普通文字不查询成员，未找到目标不静默去掉 @。no_cache 的实际效果及通知需真实 QQ 验收。

SPEC-022 已接通模型选择：组合层为群聊开启 mention schema，模型从裁剪后上下文的 member_ref 选择；程序解析为稳定账号，运行时再次校验会话范围，再走动态准备和持久发送。空数组不通知，未知引用直接拒绝。这一增量使用 TextReply(text, mentions) 并前置原生 at 段，尚未替代本节目标中的任意有序 segments；模型引用选择见 SPEC-024，真实平台验收仍未完成。

## 9. 首个TTS实现：FishAudioProvider

已选Fish Audio作为首个真实TTS供应商，保持SpeechSynthesizer接口不变。实现放在infrastructure/speech/fish_audio.py；业务只传SpeechRequest和ExecutionContext，返回AudioArtifact，不接触Fish专属模型头、音色ID和SDK类型。测试另用FakeSpeechProvider验证可替换性，首版不同时开发多家真实供应商。

首版可用异步HTTP客户端直调REST，避免接口适配依赖SDK默认值：POST https://api.fish.audio/v1/tts，Bearer鉴权，JSON请求，model请求头显式配置；text与reference_id分别对应说话文本和已配置音色。若采用官方Python SDK，锁定经过验证的版本，不混用旧Session示例。模型名缺失或未知时官方可能回落s2.1-pro，因此配置必须在本地校验，禁止空值、未知值和隐式付费回退。

管理配置映射：xiaolv_default → {provider: fish_audio, model, reference_id, format, sample_rate, profile_version}。model不是音色ID。首版使用管理员选定的已存在音色，不通过聊天创建音色或上传任意参考音频；音色失效时回退原文字或放弃，不自动换声音。

建议先请求MP3/44100Hz/128kbps的完整短句音频，保存受控文件并探测实际时长；QQ格式要求仍由适配器转码验证。HTTP响应若分块传输也仅在内部收集，完整校验后作为一条语音发送，不把音频chunk逐个发QQ。合成总时限初值20秒并取回合剩余TTL较小者；限制响应体大小，失败关闭流。认证/余额不足不重试，超时结果未知不自动再次收费合成。

当前官方提供s2.1-pro-free免费档，可作为PoC候选，但没有首音频延迟保证；正式选择须试听并测短句P95。付费模型只在管理端显式启用。供应商价格版本和计费单位独立配置，TTS费用按UTF-8输入字节估算并核对账单，不按中文字符数或音频分钟猜测。音色和API密钥在实际接入时配置，本轮没有调用收费接口。

参考地址：https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech

参考地址：https://docs.fish.audio/api-reference/sdk/python/overview

参考地址：https://docs.fish.audio/developer-guide/models-pricing/pricing-and-rate-limits

## 10. 原生引用回复

引用回复是独立的回复关系，不等于正文里粘贴一段原话，也不等于 @。LLM 最终从当前会话可见消息候选选择是否引用、引用哪条；服务端校验范围并解析平台 ID，不能让模型自由构造 QQ 消息 ID。普通文字、引用、@ 可组合，引用不自动追加 @；客户端自身是否通知仍需实测。

实现分层：入站保留 reply 关系；上下文组装展示范围内被引用消息，查不到时标记缺失，不能猜测原文；模型结构化输出引用候选；发送出口持久化引用意图并执行原有 TTL、epoch 和幂等检查；原生适配器编码 OneBot reply 段。可信映射与持久化见 SPEC-019；模型选择和在线动态映射由 SPEC-024 接通。

SPEC-023 已完成入站引用上下文表达：可见消息带 message_ref，replies 的 resolved 指向当前可见条目，missing/ambiguous 不提供推测原文。引用信息参与整体长度预算，裁剪后重新解析；同一范围内已知重复 ID 不能静默消歧。参与判断与回复使用相同规则。

参考版本 SnowLuma 的消息 ID 为有符号 int32，负数有效、零无效。element-codecs.ts 在无法解析引用时可能丢掉该段后继续发送正文；get_msg 返回的缓存事件不包含足以证明服务端序号权威性的信息。不能把 get_msg 成功或 send_msg 回执成功写成“引用已经正确显示”。在线引用需完成失效/撤回/重连场景与客户端显示验收，必要时增加适配器能力检测或上游错误反馈；不伪造引用，不自动降级掩盖丢失。

需要网络查询的发送准备必须有超时，并放在最终发送认领与有效性复核之前，防止查询卡住后补发旧回复。SPEC-020 已实现只读 prepare 接口，返回带解析快照的发送器；5 秒上限且受剩余 TTL 限制，准备后再通过账本最终复核。成员核实、模型选择与引用查询已通过 SPEC-021/022/024 接线。该接口不得用来执行付费 TTS 或外部写操作：并发重复准备是允许的，付费任务需要额外幂等与预算约束。

SPEC-024 已接通群聊与好友的引用选择：模型选可见 message_ref 或 null，程序解析唯一的会话内消息 ID；准备时 get_msg 校验 ID 和路由范围，发送后再 get_msg 读回，检查唯一匹配的原生 reply 段。查询目标失效或跨范围在发送前拒绝；读回丢段/不匹配/超时为 unknown，不重发、不另发正文。好友引用区分 user_id（目标入站消息）和 target_id（机器人发出的消息），拒绝将临时会话当作好友。缓存核对不能替代真实客户端显示验收。
