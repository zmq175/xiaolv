# 01 总体架构与技术决策

版本：v0.1，2026-09-29。性质：可进入分阶段实现的设计基线，尚未部署或完成性能验收。小绿是独立新项目；MaiBot 只用于行为和能力参考，不继承其内部架构或配置。

## 1. 已确认的产品边界

- 在 QQ 群和私聊中保持自然表达，理解上下文，能够沉默、接话与主动找话题。
- 同一 QQ 账号对应同一内部身份；群内经历、关系、黑话和私聊内容按会话隔离。通用称呼必须明确发布为共享，不因昵称相同自动关联账号。
- 文字、图片、表情包、语音纳入能力范围。LLM 决定是否语音回复及具体内容，语音供应商可替换。
- MCP 和 Agent Skills 由管理面安装、授权、发布；任何 QQ 身份都不能在聊天中执行安装或修改权限。管理员预授权的外部写能力可自动执行，范围外拒绝。
- 知识库首版支持文件上传与登记网页的手动/定时更新。
- 现有 CloudCone 为8 vCPU、8GB RAM、111GB Disk。可新增 CloudCone 专门运行 Qdrant；总预算按每月200元评估，包含原主机摊销和模型费用。
- 本轮产出技术方案，不执行采购、部署或 QQ 发消息。

## 2. 推荐的技术基线

| 决策 | 采用方案 | 理由与退出条件 |
|---|---|---|
| 应用 | Python 3.12 起步，uv 锁依赖，Pydantic v2 数据契约 | 异步模型、MCP 与 LangGraph 生态；P0 安装兼容性验证后锁定精确版本 |
| 编排 | LangGraph StateGraph，自定义群聊流程与受限工具循环 | 可观察节点和状态；不采用多 Agent 互聊架构 |
| 关系存储 | 自托管 PostgreSQL；SQLAlchemy 2、psycopg、Alembic | 人物、任务、租约、outbox 需要事务和并发；可直接使用官方 PG checkpointer |
| 检索 | 自托管单节点 Qdrant，dense+sparse | 索引独立、可重建；同机/分机均只改变连接配置 |
| 管理面 | FastAPI，服务端模板与轻量交互 | 首版单管理员，不建立独立前端工程；认证、审计和任务状态优先 |
| 后台任务 | PG 任务表、租约、幂等键；独立 worker 进程 | 复用已有数据库，暂不增加消息中间件 |
| 模型接入 | 项目自有 ModelGateway，供应商适配器 | 对齐生成、结构化输出、工具调用、视觉、ASR、TTS、embedding、rerank；不可假设全部兼容一个 API |
| 部署 | Docker Compose；QQ/SnowLuma 独立运行环境 | 固定版本与数据卷，避免把客户端生命周期混入业务进程 |

以上为本方案推荐决策，不伪称用户已逐项批准。PG 相比 SQLite 多占少量常驻资源，但节省并发任务和框架持久化的维护成本；既然与应用共用现有 VPS，并不增加托管数据库月租。首版只实现 PG repository，不同时维护 SQLite/MySQL 三套后端。

LangGraph 的 checkpointer 用于保存流程状态，不直接作为人物记忆库。官方区分 thread checkpoint 与跨流程存储；小绿长期事实采用自有领域表，方便权限、证据和纠错。[LangGraph 持久化](https://docs.langchain.com/oss/python/langgraph/persistence)

## 3. 进程和模块

```text
QQ / NTQQ + SnowLuma
          ⇅ OneBot
chat-runtime：接收 → 持久化 → 合并候选 → 决策图 → ReplyPlan
                                         ⇅
                           人物记忆 / 检索 / 能力网关
                                         ↓
                           生成媒体 → outbox → 发送

admin：配置、知识、记忆纠错、能力发布、运行检查
worker：学习、索引、清理、订阅与主动候选、备份编排
capability-runner：已发布脚本/stdio MCP 的受限执行

PostgreSQL：事实、权限、任务、费用、收发状态
Qdrant：检索索引      文件卷：原文与媒体      异地存储：备份
```

模块化单体对应一个代码库、一个核心应用镜像，不要求一个进程。管理进程拥有发布权限，聊天进程不持有管理令牌。能力执行器与聊天进程分离；首版不支持上传任意容器镜像或远程代码自动执行。IM交互是应用原生基础链路，不经过MCP：连接、事件订阅、收发消息、媒体上传下载、回执、历史查询和群资料操作都由PlatformAdapter直接调用平台协议或SDK。QQ首个实现直接连接SnowLuma/OneBot。MCP仅作为扩展能力接入，不是IM传输层，也不提供绕过统一发送的QQ出口。

```text
src/xiaolv/
  domain/          # conversation、identity、memory、knowledge、capability
  application/     # chat、proactive、learning、ingestion、delivery
  orchestration/   # LangGraph 节点与状态，不承载平台 SDK
  ports/           # platform、model、speech、retrieval、repository
  infrastructure/  # postgres、qdrant、model providers、media
  adapters/        # onebot_snowluma、replay
  admin/           # API、模板、认证
  observability/   # logger、trace、metrics
tests/             # unit、integration、replay、fault
deploy/            # Compose、配置样例、恢复脚本
```

领域代码不能导入 OneBot JSON、LangGraph saver 或数据库连接。对稳定边界建立接口，普通函数不套多层抽象。所有示例字段均在 P0 转成 Pydantic 模型及 JSON Schema，接口变更需要迁移或 schema_version。

## 4. 公共契约

| 契约 | 必要字段 | 关键约束 |
|---|---|---|
| ChatEvent | event_id, platform, bot_id, conversation_id, account_id, platform_message_id, occurred_at, received_at, segments, reply_ref, backfill, schema_version | 平台 ID 一律字符串；原始负载另存有限保留卷 |
| ScopeContext | bot_id, conversation_id, principal_id, allowed_space_ids, policy_version | 由程序构造，禁止模型或工具结果自行指定 |
| TurnContext | turn_id, epoch, observed_revision, source_event_ids, expires_at, budget_reservation_id | 一轮共用截止时间；新节点不能重置 |
| Decision | action, target_event_ids, reason_code, not_before, topic_id | action 为 SILENCE、DEFER、RESPOND、PROPOSE |
| ReplyPlan | plan_id, turn_id, parts, delivery_fallback, evidence_ids | parts 是 text、voice、image、sticker 的判别联合；LLM 输出经 schema 校验 |
| Evidence | source_id, version_id, chunk_id, locator, scope_id, text | 每次送入外部重排/模型前再次检查权限和版本 |
| SendReceipt | outgoing_id, status, platform_message_id, error_code | accepted、confirmed、failed、unknown 含义由适配器说明 |

VoicePart 包含 speech_text、voice_profile、style_hint；它是合成意图而不是可直接发送的音频。随后程序产生 AudioArtifact 并绑定该 part。ImagePart 只引用已授权媒体；图片生成可通过已发布能力提供，首版不默认新增绘图模型。

端口方法约定均为异步：PlatformPort.normalize/send/probe_capabilities；ModelGateway.generate/embed/rerank；SpeechSynthesizer.synthesize；SpeechTranscriber.transcribe；KnowledgeRetriever.search；MemoryService.resolve_context/propose/correct；CapabilityGateway.invoke。异常归类为 invalid_input、denied、unsupported、timeout、transient、permanent、unknown_side_effect，不让底层异常字符串成为业务判断依据。

## 5. 数据与一致性边界

PG 分为 app、checkpoint 两个 schema，最小权限账号分离。业务状态和 outbox 在一个 app 事务提交；checkpoint 使用其官方 saver 的事务，不宣称跨二者原子提交。以 turn_id/plan_id 唯一约束抵抗图节点重放。Qdrant 成功不等于文档已上线；只有 PG 激活的版本可被使用。

初始表组：accounts/persons/conversations/messages；conversation_state/chat_turns/outbox；assertions/aliases/relations/evidence_edges；documents/document_versions/chunks/ingestion_jobs；jobs/capability_releases/grants/tool_calls；config_versions/model_usage/budget_reservations/audit_events/media_assets。所有时间 timestamptz，ID 使用 UUID，金额使用固定精度 decimal，不用浮点累计。

关键索引在首次迁移中落实：accounts(platform,account_id)唯一；conversations(platform,bot_id,kind,external_id)唯一；messages(conversation_id,received_at DESC)；outbox(plan_id,part_index)唯一及(status,expires_at)；jobs(dedup_key)唯一及(status,available_at)；aliases(scope_id,name)非唯一；evidence_edges(source_event_id)；chunks(version_id,ordinal)唯一；grants(conversation_id,capability_id,release_id)。原始平台message_id不建立不带会话的全局唯一约束。

jobs认领用短事务的SELECT FOR UPDATE SKIP LOCKED，按available_at排序，更新lease_owner、lease_until和attempts后提交；网络与LLM调用发生在事务外。任务完成以job_id+lease_owner+lease版本条件更新，过期worker无权提交结果。MAX attempts初值3，非幂等副作用unknown不走自动重试队列。

不要求将聊天原文复制到 Qdrant。需要语义检索的是经过归纳且有出处的事件记忆与知识块；当前消息窗口直接按会话和时间从 PG 读取。Qdrant 不保存密钥，不是权威权限库。

## 6. 设计规模与性能目标

规划基线暂按1个机器人账号、10个群、少量私聊、每天1万条入站事件、最多10万知识块。它是验收用假设，不是用户已确认的实际流量。代码不写死这些数值，超出基线先压测再承诺。

初始模型并发2，后台索引并发1；群聊决策合并窗口1.5秒、最长5秒。入站处理不等待 ASR/视觉/LLM。负载基线下入站持久化 P95 目标小于500ms；依赖健康时普通闲聊从触发到发送 P95 目标小于15秒。外部模型延迟不受控，45秒后丢弃比迟到发送更重要。

这些是待验收目标。每个阶段交付回放记录、延迟分位数、费用和失败清单；未测数据不能在文档中改写为已达到。

## 7. 不做的提前建设

首版不引入 GraphRAG、图数据库、Kubernetes、Kafka、多 Agent 团队或多活集群。不把所有模型调用都包装成 Skill；Skill 是行为与资源包，语音、发送、权限和时效是基础设施。未来只有明确评测或负载证明收益，再增加组件。

## 8. 开工前验证项

P0 必须锁定兼容依赖及镜像 digest；用实际 QQ 客户端版本验证 SnowLuma 的文字、图片、表情包、语音收发和重连。模型供应商/模型 ID 尚未选定，先用网关契约与假模型跑通测试，再根据中文风格、工具调用、语音质量、海外可达性和每轮成本选择。未填写供应商的部署配置应启动失败，不自动调用未知收费服务。

## 参考资料地址

LangGraph 持久化：https://docs.langchain.com/oss/python/langgraph/persistence
