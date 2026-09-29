# 09 身份配置与提示词组织

2026-09-29。用户要求机器人名字可修改，并参考MaiBot提示词而非照搬。

## MaiBot源码观察

参考提交170453d629ba2c72259c858c565bbf0d11060d33，读取src/config/official_configs.py、src/chat/replyer/maisaka_generator_base.py及prompts/zh-CN的maisaka_chat、retro_replyer、retro_private_replyer。

可借鉴的是配置分层：bot.nickname/alias_names与personality、behavior_style、reply_style分别管理；planner和replyer各按职责组装；群聊和私聊使用不同上下文提示。这能将“是谁”“何时接话”“怎样表达”分开，避免改名需要编辑多份模板。

不能照搬的部分：

- 人设为空回退“是人类”，构建失败退回固定麦麦身份，会产生无依据的人设与静默配置错误。我们允许未填写人格细节，错误配置直接拒绝。
- 随机选择备用说话风格容易使角色不稳定；我们后续从会话风格证据里选择适用表达，不能无理由随机变换身份或语气。
- maisaka_chat要求输出分析、先搜集信息、使用reply/wait/tool_search等，是其具体工具执行架构。我们将参与、工具执行、回复计划与发送门控分层，不要求普通闲聊先搜集信息或展示推理；工具策略只列当次真实可用能力。
- retro模板对标点、括号、@和话题一刀切限制，不适合结构化ReplyPlan及原生mention。文字、mention、音频等由对应输出契约与权限校验负责。
- 将多种额外提示堆叠并捕获异常后换通用提示，会使配置问题难以定位。我们使用受版本控制的小模板和明确的输入来源，不静默降级成另一个角色。

这些是固定源码版本的设计判断，不代表对真实聊天效果的评测。

## 本项目实现

BotProfile包含name、aliases、personality、participation_style、reply_style。默认name为“小绿”，这是默认配置，不是通用提示模板中的常量。配置经XIAOLV_BOT_PROFILE JSON进入不可变profile，同一在线进程的参与和回复使用相同资料。平台账号ID保持独立，改显示名不能更改QQ账号或权限。

提示词按三层组织：稳定任务/权限/输出规则为仓库模板；管理员profile作为明确标注的配置资料加入system；会话记录作为user角色的非可信资料。人设里的花括号不会进行二次模板解释。回复字数来自实际max_reply_chars，不另写一个200常量。prompt不是权限系统，程序仍负责会话、预算和发送约束。

当前文字模板位于src/xiaolv/prompts/participation.txt和reply.txt。首版媒体/工具到来后按能力扩展输出契约，不将现阶段“只输出文字JSON”误作永久禁止工具/语音的产品规则。

配置示例（进程环境；管理UI尚未实现）：

```sh
XIAOLV_BOT_PROFILE='{"name":"阿栀","aliases":["栀子"],"personality":"对植物感兴趣，不确定的事会直说。","participation_style":"有相关信息时接话，不强行找话题。","reply_style":"温和简洁。"}'
```

名称不能为空，长度64；别名最多32个且各自非空/不超过64；人设2000、各风格1000字符。用户聊天中的“改名”文本不能写管理员profile。当前修改需重启；管理端发布/回滚、版本审计、每会话风格覆盖及学习证据以后逐项实现。没有真实模型自然度评测，不把模板检查等同于模型必然遵循。
