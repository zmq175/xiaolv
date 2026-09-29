# Fish Audio SDK可行性核验

2026-09-30。使用fish-audio-sdk==1.3.0隔离环境、Python3.12和合成httpx传输，未请求供应商、未使用真实API key、未产生模型/TTS费用。脚本不属于产品验收测试，不用它宣称TTS已接入。

命令：

```sh
UV_CACHE_DIR=/tmp/xiaolv-uv-cache uv run --with 'fish-audio-sdk==1.3.0' python tools/probes/fish_sdk_contract.py
```

实测输出：SDK1.3.0；请求/v1/tts；显式model和format传到协议；stream_returns_before_complete_body=false；503异常类型ServerError且requests_on_503=1。AsyncFishAudio类源码SHA256为8dee421ba4ad8a221752e9e8b6514695d70ba684a53c8514759c617794255d78。

结论：官方SDK可复用，提供异步客户端及httpx_client注入。不能只在返回的音频迭代器外加大小检查：该版本先通过普通httpx request完整读入响应，再返回迭代器。计划在注入HTTP传输层限制读取字节，拒绝未支持的内容编码，并通过外层原回合timeout约束总时间。SDK默认240秒不适合聊天路径；配置每次超时不替代整体deadline。503单次探针只证明该路径未重试，不等同供应商端恰好执行一次；未知结果仍需持久审计。

模型、音色显式配置；SDK主干与文档默认值存在不同描述，不根据示例默认值选生产模型。RequestOptions暴露max_retries字段，但不能仅凭字段名认为有可靠重试策略；本次观察并核对具体调用路径。

资料（官方）：

- https://docs.fish.audio/features/text-to-speech
- https://github.com/fishaudio/fish-audio-python/blob/main/src/fishaudio/client.py
- https://github.com/fishaudio/fish-audio-python/blob/main/src/fishaudio/resources/tts.py
- https://github.com/fishaudio/fish-audio-python/blob/main/src/fishaudio/core/client_wrapper.py
- https://github.com/fishaudio/fish-audio-python/blob/main/src/fishaudio/core/request_options.py

SnowLuma本地固定参考commit：1ef9a2c33023b5fcb400865c8281d2dfd190540b。packages/protocol/src/element-builder.ts中record调用makePttElem；highway/ptt-upload.ts中loadPtt调用encodeSilk并分别走群/私聊上传。由此选择适配层承接QQ编码，不在聊天业务层硬编码Silk。源码存在路径不证明当前部署的原生依赖可用，仍需真实codec/播放验收。
