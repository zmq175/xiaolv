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
| [023 引用上下文](023-quoted-context/spec.md) | Verified | 当前会话引用关系、缺失/歧义及包含元数据的长度裁剪 |
| [024 模型引用发送](024-model-quotes/spec.md) | Verified | 模型选择、会话目标核实、原生引用与读回核对；真实QQ待验收 |
| [025 会话发送配额](025-delivery-quota/spec.md) | Verified | PG冷却/滚动窗口、跨实例竞争、重启/回滚与在线限流终态 |
| [026 调用前配额预判](026-quota-preflight/spec.md) | Verified | 已限流回合跳过模型、只读预判不预留、最终认领防并发穿透 |
| [027 共享模型并发](027-shared-model-capacity/spec.md) | Verified | PG共享名额、等待不计费、取消释放、配置冲突与真实SIGKILL恢复 |
| [028 有序文字发送](028-ordered-text/spec.md) | Verified | 已解析文字/@顺序、独立引用、结构校验、回放与PG重启幂等；模型生成接线待完成 |
| [029 模型有序回复](029-model-ordered-text/spec.md) | Verified | 模型parts解析、在线文字/@/引用顺序、非法意图零发送；真实供应商与QQ待验收 |
| [030 管理HTTP认证](030-admin-auth/spec.md) | Verified | 密码库、PG会话、Cookie/CSRF/Origin、过期撤销、并发限速；网页与部署待完成 |
| [031 独立管理服务](031-admin-server/spec.md) | Verified | 密码文件初始化、真实子进程HTTP登录/停止、配置与schema门禁；浏览器页面待完成 |
| [032 管理登录页面](032-admin-login-ui/spec.md) | Verified | React同源页面、真实浏览器登录/刷新/退出、断网/限速/键盘和双视口；配置发布待实现 |
| [033 人设草稿与发布](033-profile-publication/spec.md) | Verified | HTTP草稿/发布/回滚、并发版本与持久幂等；网页编辑和聊天采用待接线 |
| [034 回合人设快照](034-turn-profile/spec.md) | Verified | 管理发布进入在线模型提示、整回合固定版本、回滚/草稿隔离、TTL与版本日志 |
| [035 人设编辑页面](035-profile-editor/spec.md) | Verified | 浏览器编辑、草稿保存与发布、同键重试和冲突恢复；双视口与真实PG验收 |
| [036 版本历史与网页回滚](036-profile-history/spec.md) | Verified | 游标历史、发布差异、版本预览与回滚、乱序/重试保护，真实PG与双视口验证 |

| [037 上下文token预算](037-context-budget/spec.md) | Verified | 现成分词、分阶段预算、完整触发/旧引用保留、PG限量读取与在线验证 |
| [038 执行授权检查点](038-execution-authorization/spec.md) | Verified | 模型阶段和发送前核验、失败关闭与取消；持久管理策略尚未接线 |

| [039 持久会话控制](039-conversation-control/spec.md) | Verified | 管理HTTP/浏览器开关、持久停用、旧回合及候选失效、跨进程时序与失败恢复 |

| [040 语音回复闭环](040-voice-reply/spec.md) | In progress | Fish官方SDK、音频产物、原生发送、管理核账及崩溃审计已通过合成服务验证；真实计费/QQ播放待验收 |

| [041 入站媒体与按需理解](041-inbound-media/spec.md) | In progress | 有序媒体清单、token预算、原生ASR及同会话派生版本持久化；下载、视觉/第三方ASR及真实验收待完成 |

Verified仅表示该规格明示范围通过验证，不代表完整首版或真实QQ上线验收。每个规格包含spec.md、plan.md、evidence.md。开发流程见CONTRIBUTING.md。
