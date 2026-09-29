# SPEC-004验证记录

2026-09-29。依赖锁定LangGraph 1.2.12，实际安装兼容Python 3.12.14。没有真实模型/IM调用。

每轮运行 `UV_CACHE_DIR=/tmp/xiaolv-uv-cache uv run --offline --locked pytest -q`：

| 行为 | Red | Green |
|---|---|---|
| 沉默 | NotImplementedError | 42 passed |
| 生成发送 | respond而非confirmed | 43 passed |
| 入口过期 | 不应调用模型却调用 | 44 passed |
| 模型晚30分钟 | 已有发送边界拦截，直接回归通过 | 45 passed |
| 模型挂起 | 测试外层1秒保险超时 | 46 passed |
| 超长回复 | 意外发送 | 47 passed |
| 空白回复 | 意外发送 | 48 passed |
| 跨会话同event_id | outgoing_id冲突 | 49 passed |
| 模型故障 | ConnectionError外泄 | 50 passed |
| 无效参与决策 | 现有图路由失败收敛满足 | 51 passed |
| 供应商超时区别回合到期 | expired而非model_error | 52 passed |
| 非确定生成并发重放 | 第二次生成导致内容冲突 | 53 passed |
| CLI假模型演示 | 模块不存在，子进程失败 | 独立CLI测试1 passed |

同步路由lambda引入线程池后出现pytest事件循环收尾等待；栈显示asyncio runner close等待，未断言已查明上游根因。将路由改为原生async后测试正常结束，无禁用用例。模型图不自动重试，发送位于图外。

限制：并发锁和结果仅限实例内；未实现持久inbox、outbox、合并候选、真实模型、平台协议、权限和费用限制。不能作为真实群上线验证。CLI脚本使用合成中文，不含真实聊天。

最终全套54 passed，ruff check/format通过，mypy src通过（11个源文件），diff检查通过。CLI子进程只传最小环境，无继承API密钥或开启LangSmith追踪。
