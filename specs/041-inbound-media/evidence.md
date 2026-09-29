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
