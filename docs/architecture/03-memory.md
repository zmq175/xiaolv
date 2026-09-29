# 03 身份、长期记忆与表达学习

版本：v0.1，2026-09-29。已确认：身份统一，记忆按会话隔离。准确认人与自然称呼优先于“记住所有信息”。

## 1. 身份与作用域

Account 唯一键是 platform+稳定账号ID；Person 是内部人物。相同 QQ 账号在各群共用 Person，不以昵称建人物主键；不同账号或平台不自动合并，管理员可确认绑定并可撤销。

Scope 分为 conversation、explicit_global、knowledge_space。群聊与每个私聊都是独立 conversation。全局可见范围仅包含机器人稳定人设，以及显式共享的称呼/资料，不包含从群聊自动学习出的经历。所有检索接口必须接收由服务端构造的 ScopeContext。

例如，甲群知道某人叫“阿树”，乙群只见过昵称“小明”：默认乙群不能直接使用甲群学到的称呼。只有管理员明确发布为通用称呼，或用户在乙群提供新证据后，才可在乙群使用。私聊事实不会因为人物ID相同而泄漏进群上下文。

## 2. 数据模型

| 表 | 核心字段 | 规则 |
|---|---|---|
| persons/accounts | person_id, platform, account_id, binding_status | 稳定账号唯一；合并保留可逆映射记录 |
| observed_names | account_id, conversation_id, display_name, observed_at | 昵称历史仅表示平台展示名 |
| aliases | person_id, scope_id, name, preferred, status, valid_from/to | 同名可指多人，不能对name加全局唯一约束 |
| assertions | subject_id, predicate, object_json, scope_id, status, evidence_type, valid_from/to, version | 自述、他述、推测分别存；不把LLM置信度当事实 |
| relations | subject_id, relation_type, object_person_id, scope_id, assertion_id | 关系必须指向断言和证据；共现不等于现实关系 |
| episodes | scope_id, start/end, participant_ids, summary, source_event_ids, status | 可检索摘要，有可追溯来源 |
| evidence_edges | target_type/id, source_event_id, source_span, source_version | 原消息撤回可沿反向索引使相关记忆失效 |
| corrections | target_id, actor, old_version, new_version, reason | 修改留痕，当前读取只使用有效版本 |
| expressions/slang | scope_id, form, meaning, context, supporting_people, evidence_ids, status | 群域生效，保留多义和反例 |

事实状态采用 proposed、active、disputed、superseded、retracted。程序不直接用累计聊天次数推断关系亲密度；称呼、互动偏好和已确认关系分开。一次玩笑里的“我爸”不能自动建立亲属关系。

## 3. 读路径

生成前固定读取当前发言人和被提及人的可见首选称呼、已确认交互偏好，预算初值800 tokens；最近40条消息受总上下文上限约束，超量按话题和引用关系裁剪。不要把全群所有人物档案塞进 Prompt。

模糊历史通过 lookup_memory 查询：先限定会话及人物候选，再检索事件摘要，PG复核状态和证据后返回。精确称呼、账号映射走 SQL；只有语义历史才走 Qdrant。查不到时允许“不记得/不确定”，而不是根据昵称猜职业或经历。

同名消歧优先级：显式@或引用账号、当前发言人、近邻上下文、已有群域别名。仍有多个候选时不写入关系，可以自然地询问指代。pronoun解析结果作为候选，不能直接变成永久身份绑定。

## 4. 写路径与学习

消息落库后只提交学习候选，不阻塞在线回复。后台每10分钟或累计50条新消息触发一批，按会话顺序提取：事实候选、称呼候选、事件摘要、表达和黑话。模型输出结构化候选及来源消息ID；程序校验证据确实存在且在同一授权范围。

用户明确自述称呼可作为较强证据激活群域别名；他述、歧义和玩笑保留候选。涉及现实身份的重要矛盾不自动覆盖，进入 disputed；管理员或新的明确纠正解决。模型自评 confidence 只参与排序。

表达/黑话起始激活门槛建议至少3次出现、2个独立发言人，并有可解释语境；单次明确释义可进入待审核候选。反例和用户纠正立即降权或撤销。机器人自己的输出不算独立学习证据，转发复读按原来源去重。门槛是评测起点，不是绝对真实性标准。

学习只形成可引用模式与含义，不修改模型参数。人格主体保持稳定；群域表达层控制句长、标点和表情偏好。管理端能预览“为什么学到这个词”，关闭某一候选、回滚版本或停止某群学习。

## 5. 纠错、撤回和遗忘

聊天里“以后叫我阿树”属于可被识别的自我称呼更新，不是管理授权；只影响当前会话内该账号的称呼。跨群共享和跨账号绑定必须通过明确的共享流程或管理面设置。不能让一个人通过聊天改别人的全局身份。

撤回消息：消息状态先改 retracted，相关事实/摘要立即标记不可用，再提交重算与索引清理。删除人物数据：首先使事实不可检索，清理原文、派生媒体、缓存、checkpoint和索引；备份按保留周期自然淘汰，恢复时重放删除记录再开放服务。

建议初始保留期：普通聊天原文30天，原始媒体7天，未使用学习候选14天，checkpoint 3天；有效长期事实持续保存直到纠正/删除。为长期事实保留必要的最小证据摘录及定位，和“原文30天”分别展示。没有保留证据且无法验证的断言降为不确定，不能继续标为高可信。

这是待上线前在管理面显式展示的保留策略，不是已获得无限期保存所有聊天的授权。截图、语音转写、视觉描述都属于同一会话数据，不能通过媒体缓存绕过删除和作用域。

## 6. 管理接口

GET /admin/persons?scope_id=... 返回当前可见档案；GET /admin/memories/{id}/evidence 展示证据；POST /admin/memories/{id}/correct 提交带 expected_version 的纠正；POST /admin/person-bindings 创建绑定；POST /admin/aliases/{id}/publish-global 显式发布共享称呼；POST /admin/forget 创建幂等删除任务并返回 task_id。写接口统一认证、审计和乐观版本检查。

## 7. 验收样本

至少准备100条身份/记忆用例，覆盖改昵称不丢人、两人同名不合并、玩笑不落事实、跨群同账号不泄露经历、私聊不出现在群回答、纠错后旧事实不可召回、删除后重建索引不复活、机器人复读不强化黑话。用户确认的隔离规则须作为集成测试，不只写在Prompt。

自然度回放另检查称呼是否合适、是否过度装熟、是否每次都叫名字。优先保证准确与克制，再扩大记忆量。
