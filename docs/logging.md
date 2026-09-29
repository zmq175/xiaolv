# 日志运行方式

应用使用Python标准库logging，业务通过getLogger和extra字段记录固定摘要；文件轮转使用标准RotatingFileHandler。项目自定义代码仅负责配置和Formatter，复用SPEC-003行格式，不自建日志系统。OpenTelemetry API/SDK负责trace/span上下文，不手写ID生成或异步上下文传播。

```text
[INFO][2026-09-29T16:20:00.123+0800][participation.py:120] chat_decision||traceid=0123456789abcdef0123456789abcdef||spanid=0123456789abcdef||schema_version=1||action=silence||__msg=参与判断完成
```

此为格式示例，不是真实运行记录。时间统一Asia/Shanghai，__msg为单等号正文；换行、回车、竖线与反斜杠转义，单条日志保持一行。来源是logging实际记录的调用文件和行号，业务不传假位置。

## 输出配置

默认INFO写stderr，stdout保留CLI JSON结果。可配置XIAOLV_LOG_LEVEL为DEBUG/INFO/WARNING/ERROR/CRITICAL；DEBUG仅用于受控诊断，不因此开放记录聊天正文。

可选XIAOLV_LOG_FILE开启本地文件输出；目录须先存在且可写，不能打开时启动返回2且不输出路径/凭据。XIAOLV_LOG_MAX_BYTES默认20MiB，XIAOLV_LOG_BACKUP_COUNT默认5，共一个当前文件和最多5个备份。按大小轮转，不是7天保留策略；总量约120MiB加单条记录边界。多个进程不能共享这个轮转文件，使用独立文件或统一采集stderr。无默认ELK/Collector服务、遥测上传或额外收费。

应用日志命名空间为xiaolv；不重设全局root logger。第三方库日志未自动并入此格式文件，需按库审核是否包含HTTP/body/凭据后再接入。重复配置只替换本模块持有的handler，不关闭调用者提供的stream。

## 链路与隐私

CLI初始化OpenTelemetry TracerProvider，但不注册网络exporter。服务启动/ready/结束各有生命周期span；每个持久回合创建trace，其模型调用各有独立子span，原生发送也有子span。入站处理为独立span。数据库队列的入站来源与后续回合尚未持久传播trace context，不能声称完整跨队列追踪；长期后台任务和跨进程关联后续实现。

无活动span时traceid/spanid为全零，表示缺少关联，不生成看似完整的随机trace。异步任务上下文隔离由OpenTelemetry实现。

当前事件包括service_started/service_ready/service_stopped/service_failed、event_received、chat_decision、model_call、outbox_transition/send_unknown/send_cancelled、turn_finished。模型日志只包含内部call_id、完成状态、usage是否已知及输入输出计数；费用真值仍在PG，不从日志推断账单。回复过期等终态记录于turn_finished.status；独立告警、指标及更多事件随后续功能补充。

禁止把聊天正文、完整prompt、模型回复、媒体地址、密钥或DSN传入日志。异常只输出类型和栈文件/行号/函数名，不格式化异常正文、不摘取源代码或局部变量。Formatter不是任意秘密检测器，业务不得将不可信内容拼入摘要或fields。未来接远程span导出时也须维持默认不自动记录异常正文的设置。

本机测试证明格式、级别、重新初始化、文件轮转、并发trace隔离和在线CLI关联行为；尚未完成磁盘故障/采集系统/生产留存与告警验收。
