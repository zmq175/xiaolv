# 实施

采用现成tiktoken分词，不自行实现tokenizer。先在模型HTTP/回放边界增加预算行为失败测试，完成独立上下文组装器；再验证必须保留的目标和引用。随后接Settings/PG有限历史读取/在线组装。外部模型均合成，不调用收费服务。

依据：[官方token计数说明](https://developers.openai.com/api/docs/guides/token-counting)，本地文本计数不等于包含工具/媒体等的完整API计数；[tiktoken](https://github.com/openai/tiktoken)提供现成编码与普通文本编码接口。本项目当前Chat Completions兼容接口不假定支持Responses计数接口。计费配额原保守字节预留不在本切片改成更激进估算。
