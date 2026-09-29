# SPEC-001：回复有效性判定

状态：Draft。公共测试接口：待维护者确认。无业务实现或测试。

## 问题

模型迟到或旧worker恢复后不能再提交过期回复。先实现最小的确定性有效性判定，不连接QQ或模型。

## 提议的公共接口

`evaluate_reply_validity(expires_at, generation_epoch, current_epoch, now) -> ValidityDecision`

输入为显式的带时区时间与epoch；输出allowed与reason（valid / expired / superseded）。该接口是提交和发送之前的必要判断，不替代数据库原子检查，也不承诺阻止已经被远端接受的消息。

## 验收条件

- AC-001：now早于expires_at且epoch一致，允许继续，reason=valid。
- AC-002：now等于或晚于expires_at，不允许，reason=expired。
- AC-003：仍在时效内但generation_epoch不等于current_epoch，不允许，reason=superseded。
- AC-004：过期且epoch失效时，固定优先报告expired，便于一致统计。
- AC-005：不同UTC偏移但表示同一时刻的时间按绝对时刻比较；无时区输入拒绝为明确输入错误。

先从AC-002的“恰好到期”行为做第一个红绿循环，再逐个实现其余行为。预期值来自以上规则，不在测试中复写实现算法。

## 非目标

不接数据库、outbox、网络取消、群权限、媒体或TTS；不提前实现完整发送服务。后续规格在事务/平台公共边界验证端到端可靠性。
