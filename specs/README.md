# 规格清单

| 规格 | 状态 | 验证范围 |
|---|---|---|
| [001 回复有效性](001-reply-validity/spec.md) | Verified | 期限、epoch、时区纯规则 |
| [002 原生发送保护](002-delivery-guard/spec.md) | Verified | 内存回放、重复及未知回执 |
| [003 日志格式](003-log-format/spec.md) | Verified | 编解码、转义及非法输入 |
| [004 文字回放](004-text-replay/spec.md) | Verified | LangGraph假模型决策和受限发送 |
| [005 启动配置](005-runtime-settings/spec.md) | Verified | 显式在线配置、参数校验及密钥隐藏 |
| [006 持久发送](006-persistent-delivery/spec.md) | Verified | PostgreSQL发送认领、恢复与迁移 |

Verified仅表示该规格明示范围通过验证，不代表完整首版或真实QQ上线验收。每个规格包含spec.md、plan.md、evidence.md。开发流程见CONTRIBUTING.md。
