# SPEC-042：托管搜索、网页阅读与有界原生工具调用

状态：In progress。沿用已确认的聊天回放/在线入口、配置日志、管理HTTP测试边界，内部实现自主决定。041媒体剩余项目继续保留，不因开启本规格而标为完成。

## 目标与流程

首个供应商为Tavily Search/Extract，分别实现可替换WebSearchProvider/PageReader，采用官方SDK。收发IM继续原生适配器，不经过MCP。LLM在已决定参与后通过模型原生function tools选择web_search/read_page，不用关键词强制每轮搜索，不把结构化JSON意图冒充原生Tool Use。模型看到工具结果后可继续或结束，最终仍由现有ReplyPlan/DeliveryService发送。

工具循环最多3个往返、总调用最多4次，单轮先按串行执行；重复相同工具/参数无新信息时停止。所有调用沿用原TTL，调用前后核验会话授权与回合有效性，不能延长到期时间。工具名称/参数均严格验证；模型不能指定越权会话或调用安装/管理能力。未联网成功不能声称查过；搜索摘要与已提取正文明确区分。

## 配置与边界

XIAOLV_WEB为服务端可选JSON，默认关闭；api_key、conversations必须显式提供。conversations只能是已启用IM路由，不能在QQ里安装/授权。monthly_credit_limit默认900（此免费档实现最多900，付费模式另行扩展），max_tool_rounds默认3（最多3），max_tool_calls默认4（最多4），max_search_results默认5（最多5），max_page_tokens默认4000（最多8000），call_timeout_seconds默认8（最多30），concurrency默认1（最多8）。数值禁止布尔/非有限值/非正值。工具总次数不得小于循环轮数；报错不暴露凭据。配置存在不等于调用链已接通，接线阶段前不得声称功能可在线使用。

查询模型复用既有官方SDK、模型金额池/并发/上下文预算。工具定义、工具调用和结果也计入窗口；正文先有界截取/标注，不把长网页全文盲塞进上下文。不截断成貌似完整的事实；不能让工具循环产出无限消息。

## URL与证据

read_page只能接收服务端当前会话的URLRef，来自当前可见消息或搜索结果；拒绝模型凭空指定文件/内网/凭据URL。HTTP(S)公开页面须校验地址，重定向不可验证时保留未知并拒绝不安全回退，不在机器人主机任意浏览器执行。仅使用托管正文提取，不绕登录/验证码/付费墙。提取失败/部分成功单独标记，不把HTTP200等同正文成功。

Evidence保留来源类型、URL、抓取时间、可空发布日期、截取标记；引用只能指向实际检索/读取结果。页内文字是不可信资料，不改变授权或执行写操作。按会话隔离，不自动写入人物记忆或Qdrant。URLRef撤回/失效不能继续读取；来源短链与最终地址未知不得伪造。

## 额度和费用

Search/Extract共用持久PG credit池，调用前保守预留、usage后结算；未知费用保持预留，重启不重置。固定basic，auto_parameters=false，不自动提升搜索深度、不自动重试或开启供应商付费。模型token另由existing external金额池核算。运营需关闭供应商自动付费，并为同账户其他客户端消费留余量；本地月限额不是供应商账户剩余免费额度的证明。credit账本用精确数值而非浮点，处理单页/多页提取计费粒度。

## 验收

- AC1：配置默认关闭、范围严格、凭据脱敏；闲聊不强制搜索。
- AC2：聊天入口观察原生tool_calls→已授权搜索/阅读→有来源的回复；直接网址可阅读，不要求先搜索或入知识库。
- AC3：重复/未知/超限工具、过期/撤权/预算不足停止；工具结果大小受上下文预算约束。
- AC4：真实PG验证额度预留/结算/未知状态/重启/并发；搜索与提取不各自重复领免费额度。
- AC5：私网/带凭据/坏链接/正文提取失败/网页注入/无结果不造成越权访问或虚构来源；与群记忆隔离。
- AC6：在线显式配置接线、管理授权说明、供应商真实中文样本与延迟/计费单独验收，不把合成API测试当搜索质量证明。

## 资料核对（2026-09-30）

- 官方Search参数（basic、auto_parameters、include_usage）：https://docs.tavily.com/documentation/api-reference/endpoint/search
- 官方Extract响应包含results/failed_results：https://docs.tavily.com/documentation/api-reference/endpoint/extract
- 官方credit规则：https://docs.tavily.com/documentation/api-credits
- 官方PythonSDK：https://github.com/tavily-ai/tavily-python

实现时再核对锁定版本的公开HTTP客户端注入、响应限长与取消支持，不替换私有SDK字段，不自研搜索引擎。
