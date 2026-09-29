# 验证记录

2026-09-30，AC1/AC2首批实现；整项仍In progress。

- 测试环境重建：原/tmp PostgreSQL/socket与tokenizer缓存不存在；从Ubuntu官方包解压PG18.6及运行库到/tmp，初始化全新测试库，仅监听Unix socket。未操作云端或真实聊天库。
- RED：在线入口经过WebSocket、PG、候选与模型HTTP后，媒体上下文缺少parts，KeyError；实施有序清单后通过。
- RED：纯媒体消息中的image+emoji_id、mface未归一为sticker，未知类型未归一为unsupported；修复后3种场景通过。平台原始file/URL/任意类型字符串不进入清单。
- RED：模型请求缺少unprocessed/unsupported说明；加入两个阶段提示词后通过。这是请求契约验证，不证明真实模型完全不会幻觉。
- 新增现有预算机制的回归：触发消息含250张图片清单时返回context_overflow，模型和发送均零调用；不以清单token替代未来真实图像/音频计费。
- 相关回归：tests/test_context_budget.py、tests/test_onebot_ingress.py、tests/integration/test_live.py，73 passed in 56.05s。
- 全部非数据库测试：347 passed in 13.54s；与上述73项有重叠，不相加冒充全量。
- 手工审查将嵌套条件改成显式顺序分支，媒体/上下文复验10 passed in 6.51s。
- ruff check、ruff format --check、mypy src通过（59个源文件）。

本轮未调用视觉/ASR服务，未下载真实QQ媒体。AC3–AC5、安全获取、媒体处理版本、原期限唤醒与供应商用量待实现；管理员表情库和图片输出仍在首版范围中。未以当前媒体清单宣称已经理解图片/表情/语音。

## 原生ASR首个实现（2026-09-30增量）

- 依据固定SnowLuma版本1ef9a2c的actions/extended.ts和modules/media-actions.ts：fetch_ptt_text按message_id转写第一段record，并经原生QQ桥返回文本。由可替换SpeechTranscriber封装，不是Skill或MCP调用。
- RED→GREEN：缺失ASR配置/接线 → 真实在线语音输入在参与决定后完成get_msg核实、fetch_ptt_text和回复上下文派生证据。
- RED→GREEN：跨群、不同发送者、不同消息ID、录音引用变化及缓存多个record原先仍生成回复；现均media_error，未调用转写与回复生成。
- RED→GREEN：空白、超3000字符、非字符串、失败响应原先仍回复或误报model_error；现media_error，无回复模型调用。
- RED→GREEN：转写期间撤权原先仍调用回复模型、最终not_sent；现立即permission_denied。转写后假时钟越过期限原先仍生成回复；现expired，不延长期限。真实asyncio挂起转写由原始deadline取消，未生成/发送。
- RED→GREEN：一条消息多个audio或重复源消息原先选择第一段/多次转写；现拒绝歧义。平台超时使用media_error固定结果，不输出错误正文。未启用路由的ASR配置在启动前拒绝。
- 转写以interpretation.kind=transcript、processor版本标记，保留原始audio和原文，不伪装成用户文字；提示明确识别可能出错且派生内容不可信。提示契约RED→GREEN不等于真实模型抗注入评测。
- 回归：全部非数据库测试355 passed in 13.94s；新增预算/沉默/关闭/旧语音/私聊边界后ASR回放12项通过。完整在线集成59 passed in 66.13s。两类范围与此前统计有重叠，不冒充整仓全量结果。
- 单条转写在3000字符以内仍须通过回复token预算；超预算只有参与模型调用，不调用回复模型。群聊和好友可用，临时会话不能作为好友处理。

仍未完成：派生结果持久化/版本及跨回合使用、安全媒体获取、图像表情理解、第三方ASR、原生服务超时/准确率/真实账号验收。原生结果目前只在本轮使用，未调用真实QQ或收费模型。

## 派生转写持久化（2026-09-30增量）

- RED→GREEN：真实在线语音识别后停止并重启服务，下一条聊天的模型请求原先丢失interpretation；现在保留原audio/空正文及派生转写，content_version从1升2，后续文字消息仍为1。没有通过内部表读取验证结果。
- RED→GREEN：相同processor的有效缓存原先重复调用get_msg/fetch_ptt_text；现在直接复用且不递增版本。旧processor版本重新识别并增加content_version。
- 管理HTTP停用，以及停用后在转写返回前恢复，分别得到permission_denied/media_error；重启后的下一轮仍看到旧音频unprocessed/version1，证明无失效写回。其他群完全没有该转写。
- 挂起原生RPC直到原期限耗尽，迟到回执不发布内容、不唤醒旧候选；下一轮仅正常回复新消息。
- RED→GREEN：保存后原先无成功日志；现仅在事务提交后记录media_interpretation_saved的turn_id/content_version/processor，不包含原音频引用和转写正文。
- 相关回归83 passed in 79.03s；包括在线聊天、媒体持久化、ASR及上下文预算。全套非数据库测试363 passed in 14.17s。期间新增日志后又单独验证跨重启与脱敏日志用例通过；范围有重叠，不相加冒充整仓全量。ruff check/format及mypy（62个源文件）通过。
- 前序778f34a的GitHub CI run36611853081已确认success（含构建、浏览器、PG/行为测试）；不将前序CI作为本次代码验证。

实现使用既有app.messages JSON派生字段，旧内容版本默认1；短事务锁序为会话状态→源消息，核对当前授权、回合/epoch、源快照与写入时截止时间。只增加内容revision，不更改聊天epoch/期限，不发起新候选。当前仅持久化最新派生结果，未实现历史派生版本审计/重新处理管理界面、删除策略或完整人物长期记忆；安全媒体获取、图像表情理解、第三方ASR和真实样本验收继续保留。

## 图片获取与视觉处理接口（2026-09-30，在途）

- 从已确认聊天回放边界验证get_msg源消息核实、get_image更新定位、HTTP传输、合成VisionDescriber及image_description派生内容；没有直接测试内部私有方法。
- RED→GREEN：下载最初接受文件协议、明文HTTP、带凭据/片段/非443端口的URL、私网/回环/组播、混合DNS、IPv6过渡地址；现均在HTTP与视觉调用前拒绝。全部DNS结果必须通过公网检查，连接固定到所选IP，Host和TLS sni_hostname保留原主机名。复用现有HTTPX和httpcore公开扩展，没有新加HTTP库。
- RED→GREEN：重定向/非200状态、非图像Content-Type、空响应、声明或实际长度超限原先流向视觉边界；现停止。流式读取跨过上限即关闭、不读取剩余块；压缩响应拒绝。默认2MiB，HTTPS/443，每次新连接，禁用代理和重试。
- RED→GREEN：源发送者、原生片段类型/文件引用不匹配，以及get_image失败状态原先仍下载；现停止。URL和签名不进入聊天模型上下文。
- RED→GREEN：HTTPX高层INFO请求日志原先包含签名URL；改用公开AsyncHTTPTransport请求接口，合成传输回放不再输出该URL。没有更改全局logger或使用HTTP库内部连接池；此验证不覆盖真实httpcore DEBUG响应头日志，应在实际部署中核对日志配置和供应商响应。
- RED→GREEN：下载期间撤权原先仍调用视觉边界；现下载后重新鉴权，阻止视觉调用。挂起响应流在原回合期限到达时关闭，未调用视觉或回复模型。
- 图片/ASR/文本/上下文相关回归64 passed in 2.33s；ruff/格式/mypy（65个源文件）通过。HTTP及视觉均为测试替身，未访问真实图片CDN或收费视觉供应商。

边界说明：ImageBytes仅表示大小受限的HTTP字节与声明类型，尚未完成图片解码、尺寸/像素校验、缩放和格式真实性验证。VisionDescriber当前只有可替换协议和测试合成实现；必须完成受限解码、视觉官方SDK与媒体token/费用预算才能接入run_live配置。当前回放每次最多一张当前触发消息图片，尚未完成多图策略、图片理解缓存复用和完整线上视觉能力。平台表情无可下载引用时仍不支持；不据此宣称已完成表情包理解。全量目标继续保留。

本增量非数据库完整回归390 passed in 14.64s；与64项相关回归重叠，不相加。本增量未重新运行PG/浏览器全量；后续接通在线图片调用时需补充PG持久化与真实模型HTTP请求验证。
