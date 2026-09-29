# 规格清单

| 规格 | 状态 | 验证范围 |
|---|---|---|
| [001 回复有效性](001-reply-validity/spec.md) | Verified | 期限、epoch、时区纯规则 |
| [002 原生发送保护](002-delivery-guard/spec.md) | Verified | 内存回放、重复及未知回执 |
| [003 日志格式](003-log-format/spec.md) | Verified | 编解码、转义及非法输入 |
| [004 文字回放](004-text-replay/spec.md) | Verified | LangGraph假模型决策和受限发送 |
| [005 启动配置](005-runtime-settings/spec.md) | Verified | 显式在线配置、参数校验及密钥隐藏 |
| [006 持久发送](006-persistent-delivery/spec.md) | Verified | PostgreSQL发送认领、恢复与迁移 |
| [007 OneBot发送](007-onebot-sender/spec.md) | Verified | 群聊/私聊原生请求与回执 |
| [008 WebSocket连接](008-onebot-websocket/spec.md) | Verified | 本地协议认证、混流、并发和断连 |
| [009 原生成员@](009-native-mentions/spec.md) | Verified | 会话内成员映射、at段及PG持久化 |

| [010 入站归一化](010-onebot-ingress/spec.md) | Verified | 群/私聊/临时会话、结构化段及时间 |
| [011 持久入站](011-persistent-inbox/spec.md) | Verified | PG去重、版本快照、隔离与故障回滚 |
| [012 持久候选调度](012-durable-candidates/spec.md) | Verified | 合并、租约、SIGKILL恢复与旧worker隔离 |

| [013 文字模型协议](013-chat-model/spec.md) | Verified | 51个协议/配置/usage审计用例；真实供应商待验收 |

| [014 模型费用账本](014-model-budget/spec.md) | Verified | PG预留、结算、竞争、跨月与SIGKILL保留 |

| [015 在线文字接线](015-live-text-service/spec.md) | Verified | 本机端到端、CLI信号、门控与恢复；真实平台待验收 |

| [016 标准日志框架](016-standard-logging/spec.md) | Verified | 标准logging、轮转、OTel回合内关联与CLI |
| [017 模型SDK](017-model-sdk/spec.md) | Verified | 官方SDK原始流、费用原值校验、取消与端到端回归 |
| [018 身份与提示词](018-configurable-persona/spec.md) | Verified | 配置改名、模板分离、长度一致、在线接线 |
| [019 原生引用回复](019-native-quotes/spec.md) | Verified | 会话内可信引用映射、reply 段、@组合与PG幂等；模型在线接线待完成 |
| [020 发送准备](020-delivery-preparation/spec.md) | Verified | 只读准备、期限与epoch复核、失败/取消语义和PG并发认领 |
| [021 动态成员核实](021-live-member-resolution/spec.md) | Verified | 当前群成员列表、严格响应校验、原生@与在线出口接线；模型选择待完成 |
| [022 模型成员选择](022-model-mentions/spec.md) | Verified | 模型member_ref选择、范围复核、动态校验与在线原生@；真实QQ待验收 |

Verified仅表示该规格明示范围通过验证，不代表完整首版或真实QQ上线验收。每个规格包含spec.md、plan.md、evidence.md。开发流程见CONTRIBUTING.md。
