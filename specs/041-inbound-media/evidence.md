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
