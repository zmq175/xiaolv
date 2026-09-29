# 验证记录

2026-09-29。本规格沿已确认配置、入站回放和发送公共边界验证；使用合成账号/消息/价格、真实本机 HTTP/WebSocket 和 PostgreSQL 18.6 隔离测试库。没有真实 QQ 登录或付费调用。

## 红绿与覆盖

- 配置先增加 live 身份、价格版本、显式月额度与会话 allowlist 测试，逐项补配置实现。用户澄清模型费用不受200元限制后，1000元模型额度与250元部署估值配置先失败后通过；不填部署估值的启动配置先失败后通过。
- 本机在线闭环、账号/迁移门控、沉默、重复/关闭会话、零额度、畸形消息、断线与有界停机逐项验证。测试调用 `run_live`，经真实网络和数据库观察输出。
- 默认 CLI：缺少 `__main__` 失败→新增入口通过。错误在线配置原先错误执行 replay→加载配置后返回2且不泄露秘密。在线子进程原先执行 replay→接入 run_live 及信号处理后，一次原生发送、SIGTERM返回0与脱敏统计通过。
- 超过一批恢复：101条历史 running 中有一条残留→循环恢复后全部expired，无模型调用/补发。追加遗留sending记录恢复unknown的已有行为回归检查。
- 畸形登录账号（bool/string/null）、3秒回合截止取消卡住模型、数据库表不可用中止服务是组合链路的回归检查，首次运行已通过，未冒称新增红绿。

AC-001 → test_settings（32项）；AC-002 → wrong_logged_in_account/schema_mismatch/invalid_login_reply/startup_recovers；AC-003 → online_text_composition/duplicate_and_disabled/live_silence/live_budget/deadline_cancels；AC-004 → invalid_frame/platform_disconnect/database_failure；AC-005 → normal_stop/platform_disconnect/live_command；AC-006 → test_cli（2项）、live_command及docs/live-text-service.md。

## 检查

实际执行：`uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy src`均通过。设置本机测试DSN运行 `uv run pytest -q --tb=short`：**283 passed in 36.21s，无跳过**。

测试DSN指向xiaolv_test，每个测试新建随机隔离库并清理。pytest未使用真实供应商密钥，CLI环境只含合成连接配置。新增在线集成16项、CLI2项。

## 边界与回滚

SPEC-015不新增数据库迁移，仍要求0005_budget。未实现生产最小数据库权限、日志框架接线与trace传播、群配额/跨进程并发、动态撤权及其他首版功能。用户提出不要自建日志框架，下一规格采用标准logging和OpenTelemetry，现有codec仅作为Formatter基础。

真实平台账号、模型结构化输出/usage、自然度、部署与备份恢复待后续验收。架构及本增量尚未同步腾讯文档。GitHub CI结果独立报告，不能用本机PASS代替。
