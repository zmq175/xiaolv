# SPEC-001 验证记录

日期：2026-09-29。用户已确认公共测试边界。

执行命令：`UV_CACHE_DIR=/tmp/xiaolv-uv-cache uv run --offline --locked pytest -q`。

| 行为 | Red | Green |
|---|---|---|
| AC-002 恰好到期 | 首次缺模块为搭建失败；建立签名后NotImplementedError，1 failed | 1 passed |
| AC-001 未到期且版本相同 | allowed断言失败，1 failed / 1 passed | 2 passed |
| AC-003 旧epoch | allowed断言失败，1 failed / 2 passed | 3 passed |
| AC-004 过期优先 | 已由前述实现满足，新增回归即通过，未伪造Red | 4 passed |
| AC-005 等价UTC偏移 | Python已支持，新增回归即通过 | 5 passed |
| AC-005 拒绝无时区参数 | 两个TypeError及一次未抛异常，3 failed / 5 passed | 8 passed |
| AC-005 夏令时重复小时 | 原生datetime同zone比较忽略fold，1 failed / 8 passed | 转UTC比较，9 passed |

测试按一个行为逐项添加；无时区行为参数化覆盖expires_at、now及两者。没有网络、睡眠、真实聊天样本或模型调用。

审查：仅测试公开函数的返回值/输入错误；结果不可变；没有私有实现断言。期限优先于epoch。时区校验在业务判断前执行。

限制：这只是确定性判定，未验证数据库原子性、平台发送、队列恢复及端到端延迟。不得视作完整防迟到方案完成。

最终工程检查：ruff check通过；ruff format --check通过（28 files）；mypy src通过（4 source files）；git diff --check通过。
