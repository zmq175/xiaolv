# ADR-0002：标准日志框架与链路上下文

状态：Accepted。2026-09-29，用户明确要求使用成熟日志框架，不自行实现日志系统。

采用 Python 标准库 logging：业务代码使用 getLogger、标准级别和 extra 字段；Handler负责输出、线程锁和文件轮转，Formatter负责用户约定的行格式。SPEC-003的codec只做表示层，不再承担日志框架职责。不并用Loguru/structlog，避免重复配置和异常路径；未来采集系统仍消费标准logging记录。

trace/span由OpenTelemetry API/SDK管理，按运行阶段创建span，Formatter读取当前上下文。默认不连接外部Collector、不上传聊天内容。持久队列跨进程的来源关联需显式携带trace context，不能假装async上下文自动穿透数据库；先实现回合内与服务阶段的可关联日志，后续补齐持久传播。

日志正文使用开发者定义的操作摘要，业务字段不包含聊天、prompt、token/key或DSN。异常默认只输出类型和无源码/局部变量的栈位置；不直接格式化第三方异常正文。stdout保留CLI结果，应用日志输出stderr，可选标准RotatingFileHandler本地轮转。一个文件由一个进程拥有，多进程部署使用各自文件或stderr采集。

依据：Python 3.12 logging HOWTO（https://docs.python.org/3.12/howto/logging.html）和OpenTelemetry Python instrumentation（https://opentelemetry.io/docs/languages/python/instrumentation/）。
