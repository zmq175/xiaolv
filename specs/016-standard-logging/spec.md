# SPEC-016：标准日志框架接入

状态：Ready。公共测试边界沿用用户已批准的日志、配置与回放/在线入口；内部实现自主。

使用标准logging Logger/Handler/Formatter，OpenTelemetry API/SDK提供span上下文。现有codec仅供Formatter重用，不自建logger、文件轮转或trace ID生成。

- AC-001：logging.getLogger('xiaolv...')产生标准LogRecord；用户格式包含实际调用文件/行、毫秒+0800时间、级别、event、traceid/spanid、业务字段和最后的__msg。无活动span时零ID表示无关联，不伪造trace。
- AC-002：INFO默认过滤DEBUG；同一进程重复配置不重复输出；stderr与可选RotatingFileHandler分别输出完整单行格式，轮转数量有上限，不关闭用户提供的stream。
- AC-003：Formatter读取OpenTelemetry活动span；并发async任务的不同trace不串线。日志不包含异常正文、源代码或局部变量，异常类型和栈位置可用于定位；保留已验证的换行/分隔符转义。
- AC-004：CLI应用配置；在线生命周期、入站摘要、回合结果、模型用量和发送状态产生结构化日志。日志只传固定摘要、计数和内部关联ID，不记录聊天正文、密钥或完整请求。模型/发送日志与当前回合span关联；接收与持久任务的跨队列传播明确留待后续规格。
- AC-005：配置级别、可选文件位置与大小/备份数合法性经公开配置接口验证。默认不安装Collector、不发遥测网络请求；日志文件每进程独立，stdout仍可解析CLI结果。

不宣称日志防泄露能检测任意错误拼接正文；业务禁止将用户内容放入日志消息。未知第三方日志不自动接入应用文件，避免直接记录请求体；后续按库审核并接入。OTLP导出、指标、磁盘预警及跨进程trace传播属于后续工程工作。
