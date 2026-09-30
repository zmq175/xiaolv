# 在线图片理解

SPEC-041仍在进行中。在线组合已接入原生OneBot图片定位、有界下载、Pillow独立进程规范化、官方模型SDK和PG派生描述存储。真实QQ、CDN/TLS及供应商模型兼容性尚待验收；不要把合成测试视为生产准确率或价格保证。

## 启用

沿用现有live服务启动步骤，在服务端设置`XIAOLV_VISION`为JSON对象。省略或设为`null`时不下载/识别图片；QQ聊天不能修改配置。密钥通过部署秘密配置注入，不提交仓库。

```json
{
  "base_url": "https://YOUR_PROVIDER/v1",
  "api_key": "REPLACE_WITH_SECRET",
  "model": "YOUR_VISION_MODEL",
  "provider": "YOUR_PROVIDER_ID",
  "price_version": "YOUR_PRICE_VERSION",
  "processor_version": "caption-v1",
  "input_cny_per_million": "1",
  "output_cny_per_million": "2",
  "image_tokens": 2048,
  "window_tokens": 8192,
  "concurrency": 1,
  "conversations": ["qq:10000:group:20000"]
}
```

示例价格、媒体token和窗口都是合成占位值，部署时必须按实际模型替换。可选`cached_input_cny_per_million`不得大于普通输入价。会话须包含在已启用路由中，所有实例的视觉并发配置须一致；不同实例共享`vision-model`并发池。视觉和文字/TTS共同使用`monthly_external_budget_cny`的external费用池，模型费用无需限制为200元。图片预留不足不发模型请求；usage缺失保留预留，避免将未知费用算作零。

模型需支持Chat Completions图像输入、`detail=low`、流式结构化JSON和`max_completion_tokens`。使用已有官方SDK，不手写模型协议。视觉请求只包含规范化JPEG与尺寸/采样信息；chat上下文收到派生描述，不含图片URL或base64。处理器标识绑定端点、供应商、模型、processor_version及规范化版本；供应商同名模型行为变化时应更新processor_version。

## 当前行为和限制

仅在LLM决定参与后处理当前触发消息的一张图片或表情，不批量读取历史图片。多图当前停止本轮，后续实现有界多图策略。描述是模型生成的不可信证据，不是已核实事实；输出超长/空白/格式错误时停止本轮。

Linux进程解码：输入最多2MiB，原图1600万像素/单边16384，输出长边512的JPEG；EXIF方向修正、透明合成白底、去元数据。动图只看首帧，不能理解整段动画。解码内存512MiB/CPU2秒/总等待3秒并受原回合期限约束。部署仍需进程身份、文件与网络隔离，资源限制不等于完整沙箱；强制故障回收验收仍待补齐。

文字字节保守估计、封装估计及媒体token预留合计受视觉窗口限制，输出与安全余量各512；媒体token需要按供应商校准。每轮始终沿用原TTL，过期不追加时间；保存核对会话授权、源快照、运行回合和epoch。描述增加消息内容版本，不触发新候选。其他会话不能读取该群的派生内容。

## 已有验收

合成平台WebSocket、真实本地模型HTTP、真实PG和合成媒体HTTP覆盖：开启后识别并持久化、重启后同会话读取且不重复下载、关闭时保留未理解状态；独立图片账本回放验证预留拒绝、实际usage结算和未知usage跨重建保留。真实模型图文能力、细字/表情/动图准确率及CDN可用性需实际环境另验。
