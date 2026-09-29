# 07 部署、成本、日志与恢复

版本：v0.1，2026-09-29。仅为部署设计，尚未登录主机、购买服务或运行真实负载。当前机器配置按用户截图：CloudCone 8 vCPU、8GB RAM、111GB Disk，续费额和剩余资源待实测。

## 1. 两档部署

| 项目 | 同机起步 | 双机隔离 |
|---|---|---|
| 现有CloudCone | QQ/SnowLuma、应用、管理、worker、PG、Qdrant | QQ/SnowLuma、应用、管理、worker、PG |
| 新增CloudCone | 无 | 单节点Qdrant，2GB验证或4GB留余量 |
| 异地备份 | 原文、PG、配置及Qdrant快照 | 同左 |
| 改动范围 | Qdrant连接本机服务 | 只改检索地址、认证和备份目标 |

两档共用应用镜像和数据库结构，不能因为分机就建设微服务集群。先用同机完成PoC；实际资源紧张或希望独立管理索引时，再采用双机方案。新增主机未获购买指令，不自动采购。

## 2. 资源与网络

现有8GB工程预算：QQ/SnowLuma约1–2GiB，应用/管理/worker约1–1.5GiB，PG约0.5–1GiB，若同机Qdrant约1–2GiB。上界不能同时分满；稳态目标不超过5–6GiB，留出页缓存、转码、索引与备份峰值。数值是测量起点，不是RSS承诺。

不在这些机器常驻LLM、embedding或大型ASR/TTS模型；走API，媒体转码及中文分词本地执行。模型并发2、TTS并发1、导入并发1；OCR按需限资源。交换空间只作应急，持续换页必须减负载。

PG只对应用网络开放。Qdrant同机用内部网络，分机走WireGuard等加密通道或TLS加来源限制，并开启API key；不假设同品牌机器自动拥有免费私网。QQ/OneBot端点有认证，只允许已知适配器连接。管理UI默认通过SSH隧道访问。备份跨主机或供应商故障域，不能只留在同一块盘。

## 3. 可执行配置结构

```yaml
runtime:
  model_concurrency: 2
  chat_ttl_seconds: 45
  knowledge_ttl_seconds: 90
  merge_window_ms: 1500
  max_merge_wait_ms: 5000
  queue_max_age_seconds: 10
delivery:
  max_parts: 2
  chat_visible_chars: 200
  knowledge_visible_chars: 600
  voice_max_seconds: 20
proactive:
  enabled_default: false
  daily_turns: 2
  min_interval_hours: 4
learning:
  batch_interval_seconds: 600
ingestion:
  concurrency: 1
```

部署产物应包含compose.base.yml、compose.local-qdrant.yml、远程Qdrant配置样例、env.example、健康检查和恢复脚本。配置中的模型ID、密钥引用、数据库地址、镜像版本为必填项，禁止用latest或默默选默认收费模型。此处不是可直接上线的完整Compose，不冒充已经验证的部署脚本。

## 4. 成本控制

长期成本公式：原机年续费/12 + 新机年续费/12 + LLM/视觉/ASR/TTS/embedding/rerank费用 + 备份/流量/税费余量 ≤ 200元。原机虽已预付，仍计入续费摊销。年付现金一次支付与月均预算分开看。

调研公开价：CloudCone 2GB/60GB为46美元/年，4GB/120GB为92美元/年；按7.5元/美元的预算系数，分别约29元和58元/月。此系数不是实时汇率，实际价格/库存/续费以下单为准。[CloudCone VPS](https://cloudcone.com/vps/)

若模型总额暂留60元、备份与余量20元，新2GB方案要求原机月均不超过约91元，新4GB方案不超过约62元。原机续费未知，不能宣称双机必然满足预算；若不满足，优先同机或减少非必要模型调用，不削掉可靠性检查。

model_usage逐次记录角色、provider、model、输入/输出token、缓存用量、音频秒数/字符数、实际或估算费用和价格版本。调用前PG事务预留最大可计费量，结束结算实际用量；跨进程共享额度。连接断开而账单未知时保守保留额度，后台核对后释放，不能一取消就当免费。

月预算70%提醒、90%停止低优先学习/主动探索，100%停止新增收费调用；先保留必要直接回复的预算分区。供应商计费和取消存在滞后，应用限额不是绝对账单硬封顶，另配置供应商消费上限并留余量。首次批量embedding单列导入预算，管理端展示预计费用再启动。

## 5. 日志规范

沿用用户确认格式，__msg单等号后为正文：

```text
[INFO][2026-09-29T16:20:00.123+0800][participation.py:120] chat_decision||traceid=0123456789abcdef0123456789abcdef||spanid=0123456789abcdef||schema_version=1||turn_id=...||action=silence||reason_code=topic_not_relevant||__msg=当前话题无需参与，保持沉默
```

统一logger接受event和结构化fields，自动获取时间、调用位置和trace上下文，业务不手拼分隔符。字段名仅允许a-z/0-9/下划线；解析先按||分段，再在第一个=处分割。值统一转义：反斜杠为\\，竖线为\u007C，换行为\n，回车为\r；解析器仅单次解码，避免原文中的字面转义二次执行。字段顺序固定基础字段在前，__msg最后。实现时用往返测试验证上述示例和注入字符串。

traceid为32位十六进制，spanid为16位，使用OpenTelemetry上下文传播；后台任务新建trace并保留源trace关联，不把长期任务所有执行复用同一个span。INFO记录决策/完成摘要，WARNING记录可恢复退化，ERROR记录需要处理的失败，DEBUG限时开启。错误日志记录error_code、异常类型、必要堆栈，不包含密钥或完整模型Prompt。

必备事件：event_received、chat_decision、model_call、tool_call、speech_synthesis、retrieval_complete、reply_expired、outbox_transition、send_unknown、memory_corrected、document_activated、capability_revoked。日志不默认记录聊天正文或语音转写，敏感内容仅在有期限的诊断模式中受控保存。

## 6. 指标与日常运行

暴露结构化指标并在管理页展示：入站速率、队列年龄、各阶段P50/P95、首token与总耗时、过期丢弃、unknown回执、每轮parts、语音成功率、检索质量样本、索引积压、月费用。群ID等高基数字段只进日志，避免每用户都变成指标标签。

首版保留本地轮转日志和轻量指标，不为了看图先安装完整ELK。日志建议7天或2GB上限，磁盘70%提醒、85%暂停大导入；阈值按111GB实际空闲调整。告警先在管理页和管理员配置的运维渠道体现，不在群内刷运维通知。

健康分live与ready：应用活着但PG不可用时不ready；Qdrant故障显示检索降级，仍允许不依赖知识的聊天；QQ断线停止发送并标记连接状态。模型供应商故障触发短暂熔断与低频探测，恢复前清理过期任务。

## 7. 备份、恢复与升级

建议PG每6小时逻辑备份，原文及配置每日增量备份，Qdrant每日快照；保留7日与4周版本，备份加密且密钥不与唯一备份放一起。目标RPO≤6小时、RTO≤2小时需要演练验证，未验收前不承诺。

Qdrant快照与PG备份可能不在同一时刻，恢复后按PG活动版本清单核对，缺失索引从原文/解析产物重建，旧索引先隔离。不能简单将任意两份最新备份拼起来就开启查询。[Qdrant快照](https://qdrant.tech/documentation/operations/snapshots/)

恢复顺序：隔离发送 → 恢复PG和文件 → 重放删除/撤权记录 → 核验或重建Qdrant → 清理过期回合 → sending/unknown进入核验 → 只读回放 → 恢复实时接收与发送。恢复备份中的旧outbox不能自动补发。

发布流程：备份 → 在测试库验证Alembic迁移 → 暂停新任务并等待有界drain → 更新固定镜像 → 健康检查与回放冒烟 → 恢复。schema采用先扩展再收缩，回滚应用需与旧schema兼容；不可逆迁移先准备恢复步骤，不能只写docker换回旧tag。

## 参考资料地址

CloudCone VPS：https://cloudcone.com/vps/

Qdrant快照：https://qdrant.tech/documentation/operations/snapshots/

## 8. 新增能力的费用与限额

Fish Audio与联网搜索沿用同一总预算，不在200元之外另算。Fish Audio按配置模型的UTF-8文本字节单价预留费用；托管搜索和页面提取按供应商credits分别计量，共享月额度。当前推荐Tavily免费档，先设900credits本地月上限，关闭自动付费；不为搜索新增VPS或SearXNG容器。免费额度按账号实际条件核实，抓取后的模型上下文成本另记。

Fish模型名必须显式且本地校验，防止官方默认/未知模型回落导致意外付费；初始合成超时20秒并服从回合剩余TTL。搜索/提取按credits而非统一次数预留，每轮最多5条搜索结果和2页正文，用户直发网址也占网页阅读额度；所有调用受统一工具次数、月额度和费用预留控制。@仍受群级消息配额和通知频率控制。

原先“模型60元”的预算示例理解为全部模型和外部工具合计预留，不额外追加搜索预算。供应商价格及免费额度改变时先修改配置并告警，不自动升级套餐。
