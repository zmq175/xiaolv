# SPEC-005证据

2026-09-29。命令 `uv run --offline --locked pytest tests/test_settings.py -q`（UV_CACHE_DIR位于/tmp）。

默认配置：NotImplementedError → 1 passed；环境覆盖：仍返回默认值失败 → 2 passed；数字与相对上限：ConfigError缺失 → 8 passed；live必填：未拒绝 → 9 passed；secret隐藏直接回归通过；URL非法协议：3 failed / 10 passed → 13 passed；未知前缀键：未拒绝 → 14 passed。

ruff与格式通过，mypy src通过（12个源文件）。不包含连通性、配置发布/回滚、权限或实际模型调用。
