# 小绿

从零构建的自然群聊 Agent。首个 IM 接入为 QQ / SnowLuma，平台交互走原生适配器；MCP 与 Agent Skills 用于扩展能力。

当前处于工程初始化阶段：已有技术方案和开发约定，尚未实现机器人、连接 QQ 或调用收费模型。完整目标包含参与判断、主动发言、人物记忆、知识库、联网搜索、图片/表情包及语音。是否语音及说什么由 LLM 决定，首个 TTS 供应商为 Fish Audio。

## 开发方式

采用 SDD（Spec-Driven Development）与 TDD。先明确规格与可观察验收条件，再沿一个公共接口逐个执行失败测试→最小实现；通过后进行审查和必要重构。不得先完成业务实现再补测试。

- [开发约定](CONTRIBUTING.md)
- [领域词汇与边界](CONTEXT.md)
- [技术方案目录](docs/architecture/00-index.md)
- [规格清单](specs/README.md)
- [首个规格：回复有效性判定](specs/001-reply-validity/spec.md)（草案，测试边界待确认）

## 本地环境

Python 3.12，使用 uv 管理环境和锁文件：

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

功能测试加入后运行 `uv run pytest`。初始化阶段没有业务实现或业务测试，不把空测试集称为通过。首次环境准备可能需要下载 Python 和依赖。

## 目录

```text
src/xiaolv/          应用代码，按规格逐步增加模块
tests/              公共接口的行为与集成测试
specs/              版本化规格、验收条件、TDD证据
docs/architecture/  技术方案基线
docs/adr/           架构决策
```

本目录是独立 Git 仓库。上一级 MaiBot、SnowLuma、research 和 design 是工作区参考，不纳入本仓库；不提交真实聊天、媒体、密钥或运行数据库。

## 状态与许可

公开仓库不表示所有功能已完成。真实平台兼容性、模型效果、延迟和费用以之后的验证报告为准。目前尚未选择开源许可证，公开可见不等于授予额外使用许可；依赖与引用遵守各自许可证。
