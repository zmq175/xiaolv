# 领域词汇与当前边界

这是从零开发的独立项目，MaiBot是参考而非待重构系统。

| 词汇 | 含义 |
|---|---|
| ChatEvent | 平台归一化后的入站消息/事件 |
| Conversation | 包含平台、bot账号、类型和目标的会话 |
| Person / Account | 内部人物 / 平台稳定账号；昵称不是主键 |
| Turn | 有原始截止时间与epoch的聊天回合 |
| ReplyPlan | LLM决定的回复目标、内容、媒介和候选parts |
| PlatformAdapter | 原生IM收发和平台交互边界，不经过MCP |
| DeliveryService | 权限、时效、幂等和发送状态管理 |
| SpeechSynthesizer | 可替换TTS边界，首个FishAudioProvider |
| WebSearchProvider / PageReader | 托管联网搜索 / 网页正文阅读 |
| Evidence | 有范围、出处和版本的回答依据 |

预算、超时、切块等值在架构文档中是实验起点，不是已测保证。技术基线推荐Python、LangGraph、PG、Qdrant和FastAPI，按切片逐步引入依赖，不预建全部模块。
