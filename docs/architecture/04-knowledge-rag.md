# 04 知识库、中文混合检索与版本更新

版本：v0.1，2026-09-29。职责是提供有权限、有版本、有出处的证据；知识回答是否检索、是否补查由聊天 LLM 决定。已确认首版支持文件上传，以及管理员登记网页的手动刷新和定时更新。

## 1. 数据与入口

知识空间 KnowledgeSpace 对指定会话授权，独立于人物记忆。管理员选择空间上传原文或登记来源；QQ 文件不自动变成全局知识，也不能通过“帮我记住”改变空间权限。

推荐文件入口为 Markdown、TXT、含文字层的PDF和DOCX。解析器接口为 parse(source)->DocumentBlocks，block 包含类型、正文、标题路径、页码/段落编号和原文坐标。Markdown/TXT 保留行号，DOCX 保留段落与表格位置，PDF 保留页码及文本块坐标。复杂表格/扫描件解析质量不足应显式标记 needs_review，不将空文本当成功；OCR 使用独立受限任务，不启动常驻大模型。

网页连接器只处理管理员登记的 URL；HTML 正文抽取后沿用同一流水线。不默认递归爬全站。普通访问失败保留旧版并显示 stale，确认删除或管理员删除才撤销文档。登录态网页需要专门连接器，不假装通用抓取即可支持。

| 表 | 主要字段 |
|---|---|
| knowledge_spaces/grants | space_id、授权会话、ACL版本 |
| sources | source_id、类型、定位、刷新策略、允许目标域名、抓取状态 |
| documents | doc_id、space_id、active_version_id、deleted_at |
| document_versions | version_id、source_hash、parser/chunker/analyzer/embedding_version、状态、错误 |
| chunks | chunk_id、version_id、ordinal、content_hash、text_ref、locator、token_count |
| ingestion_jobs | job_id、版本、stage、attempts、lease、幂等键 |

原文与解析产物用内容哈希定位的文件卷保存，PG 保存目录及权威状态；后续可替换对象存储，不改变上层接口。原文路径不直接提供给 LLM。

## 2. 可恢复的入库流水线

```text
REGISTERED → FETCHED → PARSED → CHUNKED → EMBEDDED → INDEXED
          → VALIDATED → ACTIVE
任一步失败 → FAILED_RETRYABLE 或 NEEDS_REVIEW
旧版 → RETIRED；管理员删除 → REVOKED
```

注册版本与任务在一个 PG 事务写入；任务唯一键为 source_id+content_hash+pipeline_version。每步写完成标记和产物哈希，失败可从已完成步骤恢复。embedding 缓存键必须包含模型、维度、规范化版本和正文哈希。

Qdrant point_id 使用由 version_id+chunk_id 确定的 UUID，upsert 可重试。写入后核对预期点数、版本及抽样向量维度；校验通过才允许激活。PG 的 active_version_id 是最终权威，不以 Qdrant payload 的 active 字段作为唯一依据。

发布步骤：先将新索引写完并可查询，PG 原子切换 active_version_id，随后异步撤下旧索引。查询中两路候选必须带空间过滤，并在进入重排或 LLM 前按 PG 当前 active_version_id 复核。切换窗口旧点仍可能占候选名额，使用有界补召回，不能返回已失效版本。若需要先按 payload 过滤 active，先标新点可见，再切 PG，最后清旧点；这些标志是优化提示而非授权依据。

发生权限撤销或删除时先更新 PG，后异步删索引。查询结果缓存必须带 ACL 和文档版本，撤权后失效。若 PG 不可用，私有知识回答停止，不能只相信旧索引。

## 3. 切块初值及调参方法

默认按标题、段落和表格结构切分，目标450 tokens、硬上限700、相邻块重叠60；token 用所选 embedding 对应 tokenizer 或明确保守估算器统计，中文字符数不能冒充token数。块太短先与同节合并。每块附文档标题和标题路径，但引用坐标必须指向原文正文。

表格按行组切分，每组重复列头；代码块不从语句中间硬断；FAQ 优先把问题与答案放在同块。标题路径变化形成自然边界。初版不靠 LLM 对所有文档做昂贵的语义切块。

准备至少100个带证据标注的问题，对256/450/700 tokens的方案离线比较 Recall@20、最终证据命中、引用定位、延迟和embedding费用；选择满足目标的较简单配置。切块器变更产生新 pipeline_version 并重建，不能混用索引。

## 4. 自托管中文混合召回

Qdrant collection 使用命名向量 dense 与 bm25；dense 维度从所选 embedding 配置读取，启动时校验，不固定为768。payload包含 space_id、doc_id、version_id、chunk_id、pipeline_version、可见性提示。为过滤字段建立payload索引；向量和payload按实际内存压力选择磁盘存储，先测P95再启用量化。

一次 search(query, ScopeContext, limit) 的步骤：规范化查询与必要别名扩展 → 两路召回各40 → RRF合并取30 → PG复核范围和当前版本 → 按需重排前20 → 取6–8块，合计约3500 tokens → 返回Evidence。所有数量都是起点。过滤后不足可补召回一次，不能无限增大topK。

Qdrant 支持多路 prefetch 与 RRF；它解决融合，不替你完成中文分词、权限真值和重排。[Qdrant 混合查询](https://qdrant.tech/documentation/search/hybrid-queries/)

中文词法路径明确由应用生成 sparse vector：jieba 分词与版本化词典，保留专有词、错误码和英文标识。文档与查询必须使用同一 analyzer_version。不能假设默认英文 tokenizer 自动适合中文，也不依赖 Cloud inference 才能运行。[jieba](https://github.com/fxsjy/jieba)、[FastEmbed BM25 源码](https://github.com/qdrant/fastembed/blob/main/fastembed/sparse/bm25.py)

最小 BM25 编码器仅负责词频与长度归一化，term_id 由 PG 词表分配：UNIQUE(analyzer_version,term)，ID不复用且限制uint32范围；查询未知词忽略。禁止 Python hash() 或不同进程各建词表。文档权重 tf*(k1+1)/(tf+k1*(1-b+b*length/avgdl))，k1=1.2、b=0.75起步，avgdl固定在索引版本；查询去重词权重1，IDF只由Qdrant Modifier.IDF计算一次。avgdl变化需重建，不因服务端更新IDF而自动正确。[BM25分解](https://qdrant.tech/course/essentials/day-3/sparse-retrieval-demo/)

该小编码器必须有手算样本与重启稳定性测试，不建设通用搜索框架。若兼容性验证失败，回退到 Qdrant dense + PG 对预分词文本做全文检索，应用层RRF；此时PG排名明确不称作BM25。禁止为了绕过失败直接开通收费云端推理。

首版不同知识空间可共用collection，但IDF统计可能跨空间；结果权限隔离仍强制执行。统计隔离并非payload过滤自动提供，敏感或词分布差异明显的空间需独立collection或验证目标版本的独立统计功能，避免盲目按每个用户建collection。[Qdrant索引](https://qdrant.tech/documentation/manage-data/indexing/)

## 5. Embedding、重排与模型切换

embedding经ModelGateway调用，配置provider/model/dimension/tokenizer/truncation；两个模型即使维度相同也不能混用向量。切换模型建立新collection，回放评估后切读路由；旧collection保留有限回滚窗口。必要时双写期间计算费用单独计入迁移预算。

rerank是可选接口，默认仅知识回答使用，超时或费用不足退回RRF顺序并记录降级；普通接话不重排。先筛权限再把正文发送给外部重排供应商，不能将越权候选交给模型后才过滤。重排分数不是可跨模型通用的置信度。

知识不足时允许澄清或说明没找到依据，回答中的事实与Evidence绑定。聊天表现可以自然，但不能编造资料链接或引用不存在页码。模型可改写查询再检索一次，仍在同一工具次数和TTL内。

## 6. 更新与故障

登记网页用 ETag/Last-Modified 做条件抓取并以正文hash复核；建议每日刷新起步，按来源配置。抓取器校验每次重定向的目标和解析地址，限制文件大小、耗时与重定向次数，阻止访问内部服务和本机凭据接口。运行时不接收模型指定的任意抓取目标。

导入失败保留旧活动版本；连续失败在管理页告警。资料撤销立即失效，即使Qdrant清理失败也不能再用于回答。任务死信可人工重试，重试不得重复收费embedding已缓存块。

RAG中的关系先用实体别名和PG关系表做查询扩展。首版不加GraphRAG；若跨文档多跳问题在标注集上明显失败，再单独设计关系抽取、边证据和图检索，不把“有关系”当理由。

## 7. 管理接口与验收

POST /admin/knowledge/uploads 注册文件；POST /admin/knowledge/sources 注册来源；POST /admin/knowledge/sources/{id}/refresh 刷新；GET /admin/jobs/{id} 查看阶段；POST /admin/knowledge/documents/{id}/revoke 撤销；POST /admin/knowledge/evaluate 执行离线标注集。返回 job_id，不让HTTP请求等待整条流水线。

验收必须覆盖重复导入不重复点、任务中断后恢复、改文档仅新版本可见、撤权不进入外部rerank、中文黑话与错误码可检索、坏PDF不激活空知识、向量服务宕机不拖死闲聊、切embedding可回滚。初始质量目标Recall@20≥90%、证据定位有效率100%、隔离测试0泄漏；质量阈值是待测门槛，需按实际标注集复核，不是效果承诺。

## 参考资料地址

Qdrant 混合查询：https://qdrant.tech/documentation/search/hybrid-queries/

jieba：https://github.com/fxsjy/jieba

FastEmbed BM25 源码：https://github.com/qdrant/fastembed/blob/main/fastembed/sparse/bm25.py

BM25分解：https://qdrant.tech/course/essentials/day-3/sparse-retrieval-demo/

Qdrant索引：https://qdrant.tech/documentation/manage-data/indexing/

## 8. 联网搜索与网页阅读

首版增加联网搜索。知识库查询解决管理员提供资料，联网搜索解决最新公开信息与库外问题，两者共用Evidence输出，但来源类型、权限、时效和入库规则不同。搜索结果不自动写入Qdrant或人物长期记忆；需要长期收录时由管理端登记来源并走正式入库流程。

LLM通过原生工具web_search(query, freshness, count)决定何时搜索；WebSearchProvider.search输出SearchHit列表：result_id、title、url、snippet、published_at（可空）、retrieved_at、provider。PageReader.read(url_ref)负责网页正文提取；url_ref既可来自搜索结果，也可来自当前会话用户直接发送的链接。搜索与网页阅读分开抽象，首个建议为TavilySearchProvider和TavilyPageReader，使用现成托管服务，不部署SearXNG；供应商可以分别替换，均不影响IM原生收发。

用户已选择现成托管服务。推荐先验证Tavily免费档，因为Search和Extract可覆盖搜索与直接网址阅读，减少接入工作；Exa免费档作为候选，不同时实现多家。Tavily适合免费额度内使用，不代表超额付费单价比Brave低。P0仍需用中文问题和实际网页样本测覆盖、延迟及提取成功率。官方网页提取接口：https://docs.tavily.com/documentation/api-reference/endpoint/extract

触发建议：用户要求查一下/联网确认，或涉及近期新闻、价格、版本、活动等易变信息时优先搜索；普通闲聊不强制搜索。LLM也可在已允许主动找话题时搜索，但仍受群开关、冷却与预算约束。搜索失败不得假称已查到最新内容。

首轮返回最多5条结果，必要时读取最多2个页面；一次搜索、两次阅读共用既有4次工具调用预算，追加改写搜索也计入该总数。单搜索初始超时6秒、每页8秒，取回合剩余TTL较小者，网络请求和模型生成不重置期限。只读页面可在限额内并行；普通网页首版不启动浏览器执行JS。

read_page接受当前会话的url_ref。入站链接识别器可把用户直接发送的公开HTTP(S)网址注册为短期URLRef(source=user_message, conversation_id, source_event_id, expires_at)；搜索结果注册为source=search_result。这样用户发网址就可阅读，不需要先搜索，也不需要管理员加入知识库。LLM按话题需要选择读取；用户明确要求总结链接时优先读取。普通群消息只识别链接，不无条件对所有网址收费抓取；只有链接的消息可作为待理解候选，仍经过会话开关与频率检查。

查询只发送必要关键词，不上传整段私聊、群成员档案或内部知识块。缓存按scope+规范化查询+供应商+freshness分区，TTL遵循时效与供应商存储条款；新闻可短缓存，不宣称缓存命中是刚刚重新联网。published_at缺失则留空，不能把抓取时间伪造成发布时间。

重要事实优先正文与官方来源；搜索摘要仅作线索，不伪称已读原文。资料冲突时比较发布时间和事件时间，保留不确定性。文字回复附少量实际来源链接；语音回答需附来源时由ReplyPlan明确安排文字来源part，不把URL念出来，也不绕过parts预算。

费用计入总预算：Tavily每月1000免费credits，basic搜索每次1credit，advanced每次2credit；basic Extract按官方规则每5个成功URL计1credit，失败URL不计提取费用，实施时核对账单粒度。搜索与提取消耗同一额度，不能按1000次搜索再额外无限读网页。建议本地月总额度封顶900credits留核对余量，固定basic并关闭自动升级搜索深度/自动付费，额度耗尽时停止联网并说明未读取。价格与规则：https://docs.tavily.com/documentation/api-credits

验收：实时问题能按需调用，普通闲聊不滥搜；正文与摘要区分；无结果/超时不编造；跨会话缓存不泄漏；网页提示注入不能改授权；失效URL与内网重定向被拒绝；token/调用/费用共享预算；更换FakeSearchProvider不改聊天图；结果不自动污染长期记忆。

## 9. 搜索成本复核与候选取舍

日期：2026-09-29。只核查官方公开资料，未开通账号、部署或验证CloudCone出口可用性。Brave不是唯一选择；本轮按用量宽松、每月200元总预算重新比较。

| 方案 | 当前公开额度/价格 | 对小绿的判断 |
|---|---|---|
| 私有SearXNG | 软件没有按次搜索收费；仍消耗主机和流量，上游API引擎可能另收费 | 无统一商业月额度，适合低频自用；上游可验证码/封锁，不能承诺无限稳定 |
| Tavily | 每月1000免费credits，无需信用卡；basic搜索1次1credit，advanced2credit；超额PAYG为0.008美元/credit | 省维护的免费备用；1000credit不等于1000次任意组合搜索+抽取；付费basic单价并不比Brave更低 |
| Exa | 注册20美元额度，每月10美元额度，无需付款方式；基础Search为7美元/千次，至多10结果 | 只做基础搜索时每月额度约1428次，额外读取/深搜会减少；付费单价不是更便宜 |
| Serper | 官网展示2500免费queries，未标成每月补充；Starter为50美元/5万次，6个月有效，不含税 | 长期单价低，但预付门槛和过期浪费不适合低频项目；不是Google官方API |
| Brave | Search为5美元/千次，官网每月5美元额度 | 小量其实也可能零支出；若关注额度外自由度，才需要自建或另一成本结构 |

SearXNG是元搜索服务，不维护完整网页索引，也不凭空提供搜索上游。小绿调用其JSON API，结果再由已有PageReader提取正文。不需要本地LLM、浏览器集群或另买VPS。官方JSON格式需在search.formats启用；很多公共实例未开放JSON，不把公共实例当稳定免费后端。

私有部署建议固定官方镜像版本，仅绑定本机/内部网络，设请求并发1和上游engine数量2–3，测中文结果与P95。资源配额可以从512MiB试验但不是实测需求；OOM或超时按监控调整，计入8GB资源总表。官方推荐Compose带Valkey；启用其limiter需要Valkey，不应无条件宣称只有一个容器。仅内网单调用者时可评估精简配置，但须验证所选版本依赖，应用侧限流始终保留。

自建故障应退化为无法检索或一次有预算的备用请求，不做无限重试/轮换公共实例。配置可插拔的SearxngProvider和一个HostedSearchProvider，首版最终只选择一主一可选备用，不同时开发全部供应商。备用调用同样消耗原TTL、工具和费用预算；零结果未必是故障，不每次无结果就重复花费。

本次取舍已确认：使用现成托管服务，不自建SearXNG。建议先用Tavily免费档同时提供搜索与网页提取；Exa是免费额度候选。上表保留成本比较，自建段落只作调研背景，不再属于部署计划。未开通、购买或调用服务。

官方参考：

SearXNG JSON API：https://docs.searxng.org/dev/search_api.html

SearXNG安装：https://docs.searxng.org/admin/installation-docker.html

SearXNG上游封锁与限流：https://docs.searxng.org/admin/searx.limiter

Tavily定价：https://www.tavily.com/pricing

Tavily计费：https://docs.tavily.com/documentation/api-credits

Exa定价：https://exa.ai/pricing

Serper定价：https://serper.dev/

Brave定价：https://brave.com/search/api/

## 10. 直接网址阅读的执行细节

用户发链接后，识别器建立会话内URLRef，模型通过read_page读取。首版TavilyPageReader调用POST https://api.tavily.com/extract，固定basic、format=markdown；检查results与failed_results，HTTP 200不等于所有页面成功。返回PageContent：url_ref、source_url、final_url（服务未提供则为空）、title（可空）、正文、retrieved_at、published_at（可空）、truncated、status。没有发布日期或最终跳转地址就保留未知，不虚构元数据。

只处理公开HTTP(S)内容。URL含账号密码、明显私有签名/令牌或指向内网/本机时不发给第三方；不传浏览器Cookie或后台凭据。使用托管提取时主应用只请求固定供应商端点，不自行跟随供应商返回URL下载。若未来增加本地HTTP读取器，才由本地执行每跳DNS/IP校验和连接地址绑定；不能把第三方内部重定向说成本地已逐跳验证。

公开文章/文档提取后可总结、问答或结合当前话题聊天；链接阅读不自动等于知识入库。需要登录、验证码、付费墙、纯视频或提取失败时明确返回unsupported/failed，不凭标题编造正文。首版不提供登录网页、点击表单或任意浏览器操作。若解析返回的是错误页/登录提示而非正文，应标为失败。

阅读与搜索共用原回合TTL、工具次数及月额度；用户贴长文链接不触发无限多页爬取。单页正文最多约8000tokens，按用户问题选取相关片段并标明截取，不能宣称读完超长全文。来源消息撤回后，相关URLRef与缓存失效；查询和页面内容按会话隔离。页面指令不能改变权限或触发写操作。

验收包括：纯网址输入、带“总结一下”的网址、短链接、死链、部分提取失败、内网地址、带凭据链接、登录页、超长文档、网页注入、配额耗尽；所有情况下不得谎称已读取，也不自动写入长期记忆。

官方参考：https://docs.tavily.com/documentation/api-reference/endpoint/extract
