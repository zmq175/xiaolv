# SPEC-002验证记录

2026-09-29用户确认DeliveryService边界，随后开始实现。所有测试调用公共deliver/status，外部假平台记录可观察发送内容；不读取服务内部状态。

命令：`UV_CACHE_DIR=/tmp/xiaolv-uv-cache uv run --offline --locked pytest -q`。

| 切片 | Red | Green（含SPEC-001） |
|---|---|---|
| 到期拦截 | NotImplementedError | 10 passed |
| 原生有效发送 | 返回expired而非confirmed | 11 passed |
| 旧epoch | 意外confirmed | 12 passed |
| 重复ID与状态 | 发送列表出现重复 | 13 passed |
| 并发重复 | 发送列表出现重复 | 14 passed |
| 丢失回执 | TimeoutError未收敛 | 15 passed |
| ID内容冲突 | 未抛ValueError | 16 passed |
| 等待30分钟后过期 | 已有发送前检查满足，直接回归通过 | 17 passed |
| 取消中发送 | 状态None而非unknown | 18 passed |
| 明确未发送 | 建立异常类后unknown而非not_sent | 19 passed |
| 拒绝终态可查询 | 状态None而非superseded | 20 passed |

最终pytest20通过，ruff check通过（修正import排序），ruff format通过，mypy src通过（6个源文件）。Exception宽捕获仅在已调用平台的边界使用，保守记unknown；取消单独处理并传播，明确未发送单独识别。

审查限制：内存去重和单实例串行发送只适用于当前回放切片；未实现跨进程、重启恢复、权限配额、真实平台超时预算。没有宣称生产可用。未来持久化出口必须替换状态存储和认领方式，不得简单复用此全局锁。
