# 实施计划

当前OneBotIngress已保留image/record/face等引用，PG保存ChatEvent.parts；ContextAssembler仅传text和引用关系，媒体到模型边界消失。先从真实在线输入观察模型请求，补有序parts和未理解状态；媒体引用只在当次上下文定位，原URL保留在受控入站存储，不进入模型或日志。

SnowLuma固定源码1ef9a2c中，商城表情mface会转成带emoji_id的image（packages/onebot/src/event-converter/element-codecs.ts）。归一化应保留其sticker含义，但不把summary当成图像识别结果。face本轮只表示未解释的平台表情，后续才增加可靠含义映射。

后续获取依据：同一固定版本中，modules/media-actions.ts 的 getImageInfo 会尝试刷新签名URL；getRecordInfo 可能返回空URL。actions/extended.ts 的 get_record 支持可选 out_format 并返回base64，但默认只给元数据。不能假定 file 是本机路径，也不能将平台缓存查询成功当作下载/解码成功。优先会话绑定源事件、原生查询刷新媒体定位，再在有界下载通道处理；平台转码能力需显式协商与真实样本验收。

原生ASR派生结果保存在既有app.messages.payload中，保留原事件及parts引用，并带content_version；旧JSON默认1。PostgresInterpretations沿用conversation_state优先锁序核实当前授权、turn与epoch，随后比较源消息快照再更新。单事务增加会话revision但不创建候选、不改变epoch或expires_at。测试通过在线跨重启上下文及管理HTTP撤权观察结果，不直接查询内部表作为断言。

2026-09-30下载方案核对：HTTPX已在依赖中，可通过公开请求extensions向httpcore传递sni_hostname。固定URL的IP、保留Host/TLS域名、每次下载使用独立连接且禁用代理，避免同IP不同域名复用TLS连接与DNS复解析。依据已锁定本地httpx/httpcore源码及官方说明：https://www.encode.io/httpcore/extensions/#sni_hostname 。aiohttp也支持公开resolver接口（https://docs.aiohttp.org/en/stable/client_reference.html），但本项目不为此另引HTTP栈。必须验证实际传给HTTP传输边界的IP、Host与SNI，不能只测URL字符串。
