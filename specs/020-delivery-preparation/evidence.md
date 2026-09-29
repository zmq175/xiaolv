# 验证证据

2026-09-29，沿用已授权的 DeliveryService 边界。

- 过期准备 Red：构造器没有 prepare；增加回调且最终 claim 在其后，Green。
- 准备失败 Red：ConnectionError 泄漏；记录失败并在最终有效性检查后返回 not_sent，Green。
- 卡住的准备 Red：超过测试外层 1 秒时限；增加受 TTL 约束的 5 秒准备上限后，50ms 期限测试返回 expired，Green。
- 重复请求 Red：重复/冲突请求仍执行准备，共 3 次；查询已有状态后跳过准备，但继续 claim 验证载荷，Green。
- 新 epoch（准备成功/失败）、取消准备无 unknown、已过期跳过准备均首次即通过，属于回归，不虚称红绿。
- DeliveryService 定向测试 21 passed；真实本地 PG 的双实例准备只发送一次、准备期间其他实例推进 epoch 两项首次通过。
- 全量 333 passed in 42.72s，无跳过；ruff check、格式化、mypy（35 个源码文件）与 git diff --check 通过。
- 前序 d71e178 引用回复提交的 CI 36570693167 已确认 success，不将它冒充本切片 CI。

只读准备的契约由应用组合层负责，不能当成不可信插件的执行沙箱。取消准备不写 outbox，允许之后重试只读查询；认领后崩溃仍使用原有 unknown 恢复策略。尚未接入在线动态成员查询和模型引用选择，没有真实 QQ 或付费请求。
