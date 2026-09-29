# SPEC-021：发送前动态群成员核实

状态：Verified（动态发送出口；模型选择与真实 QQ 待完成）。沿用 DeliveryService 与在线入口测试边界。

OneBotPreparation 接收服务端生成的 DeliveryRequest，按受信路由调用 get_group_member_list(group_id, no_cache=true)，将存在的 qq:账号 引用映射为原生 at 目标。禁止昵称匹配、@全体、私聊 mention；请求不得由模型直接生成账号。模型候选选择另行接线。

无 mention 不查询成员。响应必须为成功且数据为数组，成员 group_id 与请求群一致，user_id 为正整数；目标缺失或响应不可信，整条回复 not_sent，不默默删除 @。准备只读，不发送；返回的 OneBotSender 只有已解析快照，实际发送由 DeliveryService 最终 TTL/epoch 与认领约束。

引用在线解析尚未完成，因此带 reply_to 的动态准备明确拒绝，不能悄悄变普通文字。静态可信引用映射仍由 SPEC-019 验证。

验收包括动态原生 @、无成员/跨群/非法响应拒绝、私聊/all 本地拒绝、无 mention 不查询、成员查询后过期不发送和在线纯文字回归。真实群成员刷新及时性与查询后瞬间退群存在竞态，需要真实 QQ 验收；no_cache 不能当成平台原子成员资格保证。
