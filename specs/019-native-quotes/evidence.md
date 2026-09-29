# 验证证据

2026-09-29，沿用 DeliveryService 公共边界；协议侧为 RecordingRPC，持久侧为真实本地 PostgreSQL，全部使用合成消息。

## 红绿循环

1. 有效负数引用：新增单测试，Red 为 OneBotSender 不接受 reply_messages；新增可空 reply_to 与按会话可信映射、reply 段后 Green，1 passed。
2. 非法平台 ID：零、布尔值、字符串、int32 越界 5 个参数先失败（误返回 confirmed），增加严格类型/范围校验后引用相关 6 passed。
3. 跨会话/缺失目标、引用组合显式 @、私聊路由、过期/旧 epoch：回归测试首次即通过，未虚称 Red。OneBot 发送测试共 32 passed。
4. 引用重启幂等：新测试先因账本未保存引用导致相同请求 payload conflict 而失败；新增 0006_reply_to 迁移及读写后 Green。持久发送 13 passed，其中历史纯文字升级、降级再升级回归通过。

## 完整检查

- 全量 pytest：323 passed in 43.63s，无跳过；测试 DSN 指向本地隔离数据库，每个用例建立并清理独立测试库。
- ruff check 通过；format 初次发现一处排版，修正后 146 files already formatted。
- mypy：35 source files 无错误。
- git diff --check 通过。
- 前序 SDK 提交 a418591 的 GitHub CI 36569276264 已确认 success；本切片的 CI 另行核实，不混用前序结果。

未进行真实 QQ、付费模型或云部署操作。引用映射是服务端可信输入，当前在线 composition 尚未提供它，模型也尚未输出引用。平台 successful receipt 不证明客户端显示引用；SnowLuma 静默丢引用的源码限制已记录于规格与架构。迁移降级会移除引用列，不应在存在引用发送记录的生产库直接降级后重放。
