# 06 MCP、Skill与管理权限

版本：v0.1，2026-09-29。原则：通用协议和能力包可直接接入，安装、授权、执行和发送分别有明确边界。已确认：管理员预授权的外部写能力可以自动执行，无须逐次确认；未授权操作拒绝执行。

## 1. 什么由Skill承担

Skill承载任务方法、说明、资源和可选脚本，例如查询某领域资料、讲故事或整理文本。LLM按描述发现能力，需要时加载SKILL.md和必要引用文件；不能把所有Skill全文常驻Prompt。

发言时机、身份权限、TTS/ASR接口、发送去重、截止时间与日志由基础程序承担。Skill可以影响内容组织和选择语音，但不能覆盖这些规则，也不能通过正文宣布自己获得授权。

遵循Agent Skills目录格式：SKILL.md的frontmatter与正文、references、scripts、assets。规范中的allowed-tools是声明信息，不是小绿的授权真值；权限以管理面发布记录为准。[Agent Skills规范](https://agentskills.io/specification)

## 2. 最小可落地的支持范围

| 类别 | 首版实现 | 不兼容时 |
|---|---|---|
| 指令/资源型Skill | 解析元数据、按需加载、相对路径引用、版本固定 | 报出缺失文件或不支持的依赖 |
| 脚本型Skill | 管理员审核的固定脚本入口，在受限runner执行 | 不自动pip/npm安装，不允许模型临时下载执行代码 |
| 远程MCP | 注册端点、认证、发现tools/resources、按授权调用 | 能力缺失或认证失败显示unavailable |
| stdio MCP | 管理端固定启动命令和环境，在runner内运行 | 无法满足依赖则不发布 |
| 浏览器/桌面型Skill | 仅在对应工具已配置并审核时可用 | 显式标unsupported，不承诺任意Skill开箱即用 |

内置宿主工具包括read_skill_resource、run_skill_script、search_knowledge、lookup_memory。IM连接和交互全部走原生PlatformAdapter，不经过MCP；普通回复经ReplyPlan/DeliveryService发送。LLM确需选择的平台查询或动作以原生函数工具暴露，复用服务端授权规则后直接调用适配器，不需套一层MCP。聊天运行时不加载QQ/IM收发MCP服务器，runner不持有平台凭据。MCP只负责其他扩展能力，其资源读取同样需要范围和大小限制。

## 3. 包生命周期

```text
导入来源/固定commit或包 → 校验路径与哈希 → 静态清单
 → 管理员审查权限/依赖 → 沙箱测试 → 发布不可变版本
 → 按会话授权 → 启用 → 撤销/回滚
```

管理端可以登记Git来源的固定commit或上传归档，下载在管理任务中完成。检查目录穿越、符号链接、压缩炸弹、可执行入口与资源上限。安装时不运行包内脚本。升级创建新release并显示权限差异，不覆盖正在使用的文件。

capability_releases保存capability_id、version、content_hash、source_ref、runtime_image_digest、entrypoints、network_targets、secret_bindings、status。grants保存conversation_id、allowed_principal_ids、capability_id、release_id、allowed_actions、target_constraints、effect_class、limits、policy_version。秘密只保存引用，实际secret挂载给授权runner，不进入Prompt和Skill文本。

聊天进程只读取active release元数据，无法写包目录、创建发布或管理凭据。QQ发言者即使是管理员账号，也无权调用管理API。即时撤权先更新PG并递增policy_version，清除能力目录缓存；每次执行重新检查，长任务提交副作用前也检查。

## 4. 执行网关

invoke(capability_id, action, args, ExecutionContext)依次执行：schema校验 → 服务器scope授权 → release可用性 → 费用与次数预留 → 根据预授权副作用策略执行或拒绝 → runner → 结果大小和媒体引用校验 → 用量结算和审计。

tool_calls字段为call_id、turn_id/task_id、release_id、scope_id、args_hash、effect_class、idempotency_key、state、result_ref、cost、deadline。相同调用的重试只在明确幂等或确认未执行时允许；外部API不支持幂等且回执未知，标记unknown并人工核验，不自动重做。

工具输出是低信任资料。它可以提供结果，不能要求安装新包、扩大授权、提取其他群数据或更换系统指令。超大结果截取带出处的摘要或分页，不能把整个远程响应塞入上下文。

远程MCP按其认证机制配置，区分应用访问令牌和服务器令牌，不把用户令牌任意透传；管理员登记端点也要检查重定向和内网目标。具体实现锁定官方SDK兼容版本，网关隔离协议变化。[MCP安全实践](https://modelcontextprotocol.io/specification/latest/basic/security_best_practices)

## 5. 脚本执行器

首版只运行管理员审核的固定入口，不提供通用裸shell工具给聊天模型。参数通过结构化argv/JSON传递，不拼接shell命令。runner以非root身份、只读包目录、临时工作目录、CPU/内存/PID/时间限制执行；不挂Docker socket、主机目录或主库凭据。

实现可使用预先部署的固定runner容器与本地受限RPC；管理端构建依赖镜像，聊天进程不能创建特权容器。默认无网络，确需联网的能力使用管理员配置的出口代理和目标规则；容器内必须阻断绕过代理的直连，单靠HTTP客户端白名单不算网络隔离。

资源初值每次脚本256MiB内存、15秒、最多一个并发；具体能力管理员调整。脚本只返回结构化结果和受控artifact，主应用对返回文件检查路径与大小。这个方案降低已审核脚本的风险，不宣称普通容器足以安全运行任意恶意代码；未审核第三方代码不进入聊天执行池。

## 6. 预授权写操作自动执行

用户已选择预授权自动执行，因此首版正常写操作不进入逐次审批。管理员发布grant时必须明确：哪个能力版本、哪些动作、哪些会话和调用者、允许的外部目标及参数约束、次数/费用上限、失效时间。只有scope、目标和调用者同时满足才能自动执行。

例如，授权某群中指定成员向指定日历创建事件，不代表全群任何人都能改其他日历；授权创建不隐含删除权限。默认不提供任意HTTP写入或任意SQL工具。模型可以决定何时调用已授权动作，但网关逐次验证，缺少授权时返回denied，不能自己发起安装或修改grant。

写调用记录intent及幂等键后再执行，服务支持幂等时传给服务。参数哈希、release、授权版本与外部回执持久化，进程恢复先查询状态而不是重做。外部不支持幂等且结果未知，进入unknown，管理员在任务页核验；这属于处理异常，不是每次调用都审批。

管理员撤权使后续执行停止；已被远端接受的副作用无法凭本地取消保证撤销，需要该能力显式支持补偿操作，且补偿本身也要授权。取消聊天回合不自动回滚外部写入。

普通短时动作服从回合TTL。超过即时聊天时间的动作转成独立task_id，只有发布清单允许异步才可继续；任务有自己的截止时间、预算和通知策略。不得通过转后台绕过授权、无限延时或补发过期草稿。管理面可以将个别能力设置为需确认，但它是可选策略，首版默认按用户选择使用预授权自动执行。

## 7. 管理页面与API

首版单管理员账号，密码哈希保存，安全cookie、CSRF校验、登录限速；默认仅本机/VPN入口访问，经SSH转发即可使用。聊天进程无管理session。以后公开访问再增加HTTPS和更强身份认证，不把管理端直接暴露给QQ群用户。

| 页面 | 必须可操作的内容 |
|---|---|
| 运行概览 | 连接状态、队列年龄、模型延迟、丢弃/unknown、预算 |
| 会话设置 | 人设、主动开关、静默时段、媒体偏好、能力授权 |
| 人物与学习 | 别名、证据、纠正、共享称呼、候选启停 |
| 知识库 | 上传/来源、阶段、活动版本、刷新、撤销 |
| 能力管理 | 导入、检查、测试、版本差异、授权、发布、撤销 |
| 任务与执行记录 | 自动执行的目标与参数、执行结果、未知回执核验 |
| 模型与配置 | 供应商绑定、音色、预算、配置校验/发布/回滚 |

管理写接口带expected_version和Idempotency-Key；冲突返回409，非法配置返回422，异步操作返回202+job_id。配置draft通过校验后发布不可变版本，运行时绑定版本；紧急禁用和撤权即时生效，普通风格变更从下一轮生效。

## 8. 验收

必须验证群内安装请求无管理副作用、Skill文本不能自授权、其他群媒体不可读取、路径穿越被拒绝、脚本不能访问主库密钥、撤权后旧worker不能继续调用、MCP token不出现在日志、版本回滚可用、写操作结果未知不自动重试。配置错误必须在发布前展示具体字段，不能等上线才以模型错误掩盖。

## 参考资料地址

Agent Skills规范：https://agentskills.io/specification

MCP安全实践：https://modelcontextprotocol.io/specification/latest/basic/security_best_practices
